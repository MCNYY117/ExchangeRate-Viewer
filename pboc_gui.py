import os
import re
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests


class PBOCError(RuntimeError):
    """抓取或解析失败。消息会直接显示给用户，所以写人话。"""


class PBOCExchangeRate:
    """人民币汇率中间价获取器。

    数据来自中国外汇交易中心受权公布、发布在央行官网的公告页。
    公告没有 API，只能抓网页 —— 所以解析是基于 HTML 结构 + 中文文案的正则，
    站点改版就会失效。这里尽量把失败说清楚，而不是悄悄返回空。
    """

    BASE_URL = "https://www.pbc.gov.cn"
    LIST_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125217/125925/index.html"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })
        # 刻意不设 Accept-Encoding。requests 会按实际装了的解码器自己决定；
        # 手写一个 "br" 而环境里没有 brotli，响应要么解码失败要么乱码。

    def _fetch_html(self, url: str) -> str:
        """取一个页面。失败一律抛 PBOCError，不吞异常。"""
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise PBOCError(f"访问失败：{exc}") from exc
        # 站点没声明 charset，强制按 UTF-8 解，否则中文会乱
        resp.encoding = "utf-8"
        return resp.text

    def get_announcement_list(self) -> List[Tuple[str, str]]:
        """获取公告列表，返回 [(YYYY-MM-DD, url), ...]，按日期去重。

        网络失败会抛 PBOCError；抓到了页面但一条都没解析出来则返回空列表
        （那是「页面结构变了」，和「连不上」是两回事，要分开告诉用户）。
        """
        html = self._fetch_html(self.LIST_URL)

        # 多种正则模式，按优先级尝试
        patterns = [
            # 模式1：精确匹配 "2026年7月3日中国外汇交易中心受权公布人民币汇率中间价公告"
            r'(\d{4}年\d{1,2}月\d{1,2}日)中国外汇交易中心受权公布人民币汇率中间价公告.*?href="([^"]+)"',
            # 模式2：匹配 "人民币汇率中间价公告" 但可能缺少部分文字
            r'(\d{4}年\d{1,2}月\d{1,2}日).*?人民币汇率中间价公告.*?href="([^"]+)"',
            # 模式3：直接匹配链接和日期（更宽松）
            r'href="(/zhengcehuobisi/125207/125217/125925/[^"]+)".*?>(\d{4}年\d{1,2}月\d{1,2}日)',
        ]

        announcements: List[Tuple[str, str]] = []
        for pattern in patterns:
            matches = re.findall(pattern, html)
            if not matches:
                continue
            first = matches[0]
            if len(first) != 2 or not isinstance(first[0], str):
                continue
            # 模式 1/2 是 (日期, URL)，模式 3 是 (URL, 日期)
            dated_first = "年" in first[0]
            for a, b in matches:
                date_str, url = (a, b) if dated_first else (b, a)
                date_standard = self._parse_date(date_str)
                if date_standard:
                    announcements.append((date_standard, self._normalize_url(url)))
            if announcements:
                break

        # 正则都没匹配上，退回扫所有 <a> 标签
        if not announcements:
            for url, text in re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html):
                if "人民币汇率中间价" not in text:
                    continue
                date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', text)
                if not date_match:
                    continue
                date_standard = self._parse_date(date_match.group(1))
                if date_standard:
                    announcements.append((date_standard, self._normalize_url(url)))

        # 按日期去重，保留第一次出现的
        seen = set()
        unique = []
        for date, url in announcements:
            if date not in seen:
                seen.add(date)
                unique.append((date, url))
        return unique

    def _normalize_url(self, url: str) -> str:
        """补全为绝对 URL"""
        if url.startswith("http"):
            return url
        if url.startswith("/"):
            return self.BASE_URL + url
        return self.BASE_URL + "/" + url

    def _parse_date(self, date_str: str) -> Optional[str]:
        """中文日期 → YYYY-MM-DD"""
        try:
            return datetime.strptime(date_str, "%Y年%m月%d日").strftime("%Y-%m-%d")
        except ValueError:
            return None

    def get_exchange_rates(
        self,
        date_str: Optional[str] = None,
        announcements: Optional[List[Tuple[str, str]]] = None,
    ) -> Optional[Dict[str, float]]:
        """获取指定日期（默认最新）的中间价，统一成 1 人民币 = X 外币。

        announcements 可以直接把调用方已经抓好的列表传进来 ——
        原来这里每次都重新抓一遍列表页，而调用方内存里明明已经有了。
        """
        if announcements is None:
            announcements = self.get_announcement_list()
        if not announcements:
            return None

        candidates = sorted(announcements, key=lambda x: x[0], reverse=True)

        if date_str is None:
            target_url = candidates[0][1]
        else:
            matches = [url for d, url in candidates if d == date_str]
            if not matches:
                return None
            target_url = matches[0]

        html = self._fetch_html(target_url)

        # 提取公告正文
        full_text = ""
        patterns = [
            r'<p[^>]*>(.*?)</p>',
            r'<div[^>]*class="content"[^>]*>(.*?)</div>',
            r'<td[^>]*>(.*?)</td>',
            r'<div[^>]*id="content"[^>]*>(.*?)</div>',
        ]
        for pattern in patterns:
            for match in re.findall(pattern, html, re.DOTALL):
                clean = re.sub(r'<[^>]+>', '', match)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if "人民币汇率中间价" in clean or "对人民币" in clean:
                    full_text += clean + " "

        # 没提到就整页清一遍，再按关键字切一段
        if not full_text:
            html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.DOTALL)
            html_clean = re.sub(r'<[^>]+>', ' ', html_clean)
            html_clean = re.sub(r'\s+', ' ', html_clean).strip()
            idx = html_clean.find("人民币汇率中间价")
            if idx != -1:
                full_text = html_clean[max(0, idx - 50): idx + 800]

        if not full_text:
            return None

        return self._parse_and_convert(full_text)

    def _parse_and_convert(self, text: str) -> Dict[str, float]:
        """解析公告文本，统一成 1 人民币 = X 外币。

        ★ 必须带上「单位数」。公告里多数币种写作 `1美元对人民币7.1元`，
          但日元、韩元写作 `100日元对人民币4.5元` —— 前者一行里的数字是 1，
          后者是 100。老代码把 1 写死在正则里，于是这两种货币**永远抓不到**。
        """
        rates: Dict[str, float] = {}

        # 主格式：<单位数><币种>对人民币<汇率>元
        for units_str, currency, rate_str in re.findall(
                r'(\d+)\s*([一-龥]+?)\s*对人民币\s*([\d.]+)\s*元', text):
            try:
                units = int(units_str)
                rate = float(rate_str)
            except ValueError:
                continue
            if units <= 0 or rate <= 0:
                continue
            currency = currency.strip()
            if currency:
                rates[currency] = units / rate

        # 兜底：万一日后公告改用「人民币N元对X外币」的写法。
        # 只在主格式一条都没解析出来时才跑，避免两种格式对同一币种写入不同值。
        if not rates:
            for units_str, rate_str, currency in re.findall(
                    r'人民币\s*(\d+)\s*元对\s*([\d.]+)\s*([一-龥]+?)(?:[，。、；\s]|$)', text):
                try:
                    units = int(units_str)
                    rate = float(rate_str)
                except ValueError:
                    continue
                if units <= 0:
                    continue
                currency = currency.strip()
                if currency:
                    rates[currency] = rate / units

        return rates


class ExchangeRateGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("人民币汇率中间价查询")
        self.root.geometry("650x550")
        self.root.resizable(True, True)

        self.extractor = PBOCExchangeRate()
        self.rates_data: Optional[Dict[str, float]] = None
        self.current_date: Optional[str] = None
        self.announcements: List[Tuple[str, str]] = []
        self.available_dates: List[str] = []
        self.busy = False

        # --- 顶部：日期选择 ---
        frame_top = ttk.LabelFrame(root, text="选择日期", padding=10)
        frame_top.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame_top, text="日期 (YYYY-MM-DD):").grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.date_var = tk.StringVar()
        self.date_entry = ttk.Entry(frame_top, textvariable=self.date_var, width=15)
        self.date_entry.grid(row=0, column=1, padx=5, pady=5)

        self.btn_refresh = ttk.Button(frame_top, text="刷新公告列表", command=self.refresh_announcements)
        self.btn_refresh.grid(row=0, column=2, padx=5, pady=5)

        self.btn_latest = ttk.Button(frame_top, text="获取最新", command=self.fetch_latest, state="disabled")
        self.btn_latest.grid(row=0, column=3, padx=5, pady=5)

        self.btn_fetch = ttk.Button(frame_top, text="查询该日汇率", command=self.fetch_selected, state="disabled")
        self.btn_fetch.grid(row=0, column=4, padx=5, pady=5)

        self.date_info_label = ttk.Label(frame_top, text="请点击“刷新公告列表”加载可用日期", foreground="blue")
        self.date_info_label.grid(row=1, column=0, columnspan=5, sticky="w", pady=5)

        # --- 中间：结果显示（表格） ---
        frame_mid = ttk.LabelFrame(root, text="汇率数据", padding=10)
        frame_mid.pack(fill="both", expand=True, padx=10, pady=5)

        columns = ("货币", "汇率 (1人民币= X外币)")
        self.tree = ttk.Treeview(frame_mid, columns=columns, show="headings", height=15)
        self.tree.heading("货币", text="货币")
        self.tree.heading("汇率 (1人民币= X外币)", text="汇率 (1人民币= X外币)")
        self.tree.column("货币", width=150, anchor="center")
        self.tree.column("汇率 (1人民币= X外币)", width=200, anchor="center")

        scrollbar = ttk.Scrollbar(frame_mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- 底部：操作按钮 ---
        frame_bottom = ttk.Frame(root)
        frame_bottom.pack(fill="x", padx=10, pady=10)

        self.btn_export = ttk.Button(frame_bottom, text="导出到桌面 Excel", command=self.export_excel, state="disabled")
        self.btn_export.pack(side="left", padx=5)

        self.btn_clear = ttk.Button(frame_bottom, text="清空显示", command=self.clear_display)
        self.btn_clear.pack(side="left", padx=5)

        self.status_var = tk.StringVar()
        self.status_var.set("就绪，正在加载公告列表...")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", padx=10, pady=5)

        # 启动就去抓，但**不阻塞界面** —— 见 _run_async
        self.refresh_announcements()

    # ------------------------------------------------------------------ 异步管线

    def _run_async(self, work, on_success, busy_text: str) -> None:
        """在工作线程里跑 work()，结果回到主线程交给 on_success。

        ★ 所有网络请求都必须走这里。原来的写法是在 Tk 主线程里直接 requests.get()，
          单次超时 15 秒，而启动路径要连发三次请求 —— 网络一慢，窗口就有最长
          约 45 秒完全无响应（`root.update()` 只是重绘，挡不住这个）。
        """
        if self.busy:
            messagebox.showinfo("提示", "正在请求中，请稍候...")
            return

        self.busy = True
        self._set_buttons_busy()
        self.status_var.set(busy_text)

        def deliver(callback):
            # 窗口可能在请求途中被关掉，那时 after() 会抛 TclError
            try:
                self.root.after(0, callback)
            except tk.TclError:
                pass

        def runner():
            try:
                result = work()
            except Exception as exc:  # 网络、解析，任何东西都别让线程静默死掉
                deliver(lambda e=exc: self._finish(on_success, None, e))
            else:
                deliver(lambda r=result: self._finish(on_success, r, None))

        threading.Thread(target=runner, daemon=True).start()

    def _finish(self, on_success, result, error) -> None:
        self.busy = False
        self._set_buttons_idle()
        if error is not None:
            self.status_var.set(f"出错：{error}")
            messagebox.showerror("出错", str(error))
            return
        on_success(result)

    def _set_buttons_busy(self) -> None:
        for btn in (self.btn_refresh, self.btn_latest, self.btn_fetch, self.btn_export, self.btn_clear):
            btn.config(state="disabled")

    def _set_buttons_idle(self) -> None:
        """没有请求在跑时，按当前数据状态恢复按钮可用性。"""
        has_dates = bool(self.available_dates)
        self.btn_refresh.config(state="normal")
        self.btn_latest.config(state="normal" if has_dates else "disabled")
        self.btn_fetch.config(state="normal" if has_dates else "disabled")
        self.btn_export.config(state="normal" if self.rates_data is not None else "disabled")
        self.btn_clear.config(state="normal")

    # ------------------------------------------------------------------ 三个动作

    def refresh_announcements(self) -> None:
        """刷新公告列表，完成后顺手取回最新汇率。"""
        def work():
            items = self.extractor.get_announcement_list()
            items.sort(key=lambda x: x[0], reverse=True)
            return items

        def done(items):
            self.announcements = items
            self.available_dates = [d for d, _ in items]

            if not self.available_dates:
                self.date_info_label.config(text="未获取到任何公告，请检查网络或稍后重试", foreground="red")
                self.status_var.set("公告列表为空，请检查网络或网站是否可访问")
                messagebox.showerror("错误", "未能获取到任何公告列表。\n请检查网络连接或稍后重试。")
                return

            self.date_var.set(self.available_dates[0])
            self.date_info_label.config(
                text=f"可用日期: {self.available_dates[-1]} ~ {self.available_dates[0]} "
                     f"(共{len(self.available_dates)}条)",
                foreground="green",
            )
            self.status_var.set(f"公告列表加载成功，最新日期: {self.available_dates[0]}")
            self.fetch_latest()

        self._run_async(work, done, "正在获取公告列表...")

    def fetch_latest(self) -> None:
        """获取最新一期汇率。"""
        if not self.available_dates:
            messagebox.showwarning("提示", "请先刷新公告列表")
            return

        def work():
            # 把已经抓到的列表传进去，省掉一次多余的网络请求
            return self.extractor.get_exchange_rates(announcements=self.announcements)

        def done(rates):
            if not rates:
                self.status_var.set("获取失败")
                messagebox.showerror("错误", "获取最新汇率失败，可能页面结构已变化")
                return
            self.rates_data = rates
            self.current_date = self.available_dates[0]
            self._display_rates(rates)
            self.status_var.set(f"成功获取 {self.current_date} 的汇率")

        self._run_async(work, done, "正在获取最新汇率...")

    def fetch_selected(self) -> None:
        """获取指定日期的汇率。"""
        if not self.available_dates:
            messagebox.showwarning("提示", "请先刷新公告列表")
            return

        date_str = self.date_var.get().strip()
        if not date_str:
            messagebox.showwarning("提示", "请输入日期")
            return
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            messagebox.showwarning("提示", "日期格式错误，请使用 YYYY-MM-DD")
            return
        if date_str not in self.available_dates:
            messagebox.showwarning(
                "提示",
                f"没有 {date_str} 的公告数据\n可用范围: {self.available_dates[-1]} ~ {self.available_dates[0]}",
            )
            return

        def work():
            return self.extractor.get_exchange_rates(date_str, announcements=self.announcements)

        def done(rates):
            if not rates:
                self.status_var.set("获取失败")
                messagebox.showerror("错误", f"获取 {date_str} 汇率失败，可能页面结构已变化")
                return
            self.rates_data = rates
            self.current_date = date_str
            self._display_rates(rates)
            self.status_var.set(f"成功获取 {date_str} 的汇率")

        self._run_async(work, done, f"正在获取 {date_str} 汇率...")

    # ------------------------------------------------------------------ 显示与导出

    def _display_rates(self, rates: Dict[str, float]) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for currency, rate in sorted(rates.items(), key=lambda x: x[0]):
            self.tree.insert("", "end", values=(currency, f"{rate:.6f}"))

    def clear_display(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.rates_data = None
        self.current_date = None
        self.rates_data = None
        self._set_buttons_idle()
        self.status_var.set("已清空")

    def export_excel(self) -> None:
        if not self.rates_data:
            messagebox.showwarning("提示", "没有数据可导出")
            return

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop):
            desktop = os.getcwd()

        filename = f"人民币汇率_{self.current_date}.xlsx" if self.current_date else "人民币汇率.xlsx"
        filepath = os.path.join(desktop, filename)

        if os.path.exists(filepath):
            if not messagebox.askyesno("文件已存在", f"{filename} 已存在，是否覆盖？"):
                return

        try:
            sorted_items = sorted(self.rates_data.items(), key=lambda x: x[0])
            df = pd.DataFrame(sorted_items, columns=["币种", "汇率"])
            df["汇率"] = df["汇率"].apply(lambda x: round(x, 6))
            with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="汇率")
            messagebox.showinfo("导出成功", f"已导出到:\n{filepath}")
            self.status_var.set(f"导出成功: {filepath}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            self.status_var.set("导出失败")


def main():
    root = tk.Tk()
    app = ExchangeRateGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
