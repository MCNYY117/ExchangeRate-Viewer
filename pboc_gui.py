import os
import re
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd


class PBOCExchangeRate:
    """中国人民银行人民币汇率中间价获取器（增强版）"""

    BASE_URL = "https://www.pbc.gov.cn"
    LIST_URL = "https://www.pbc.gov.cn/zhengcehuobisi/125207/125217/125925/index.html"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        })

    def get_announcement_list(self) -> List[Tuple[str, str]]:
        """
        获取公告列表（改进版，支持多种匹配模式）
        Returns:
            List[Tuple[date, url]]: 日期和对应的公告URL
        """
        try:
            resp = self.session.get(self.LIST_URL, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text
        except Exception as e:
            print(f"[错误] 获取公告列表失败: {e}")
            return []

        # 多种正则模式，按优先级尝试
        patterns = [
            # 模式1：精确匹配 "2026年7月3日中国外汇交易中心受权公布人民币汇率中间价公告"
            r'(\d{4}年\d{1,2}月\d{1,2}日)中国外汇交易中心受权公布人民币汇率中间价公告.*?href="([^"]+)"',
            # 模式2：匹配 "人民币汇率中间价公告" 但可能缺少部分文字
            r'(\d{4}年\d{1,2}月\d{1,2}日).*?人民币汇率中间价公告.*?href="([^"]+)"',
            # 模式3：直接匹配链接和日期（更宽松）
            r'href="(/zhengcehuobisi/125207/125217/125925/[^"]+)".*?>(\d{4}年\d{1,2}月\d{1,2}日)',
        ]

        announcements = []
        for pattern in patterns:
            matches = re.findall(pattern, html)
            if matches:
                # 如果是模式1或2，顺序是 (日期, URL)
                if len(matches[0]) == 2 and isinstance(matches[0][0], str) and "年" in matches[0][0]:
                    for date_str, url in matches:
                        full_url = self._normalize_url(url)
                        date_standard = self._parse_date(date_str)
                        if date_standard:
                            announcements.append((date_standard, full_url))
                # 如果是模式3，顺序是 (URL, 日期)
                elif len(matches[0]) == 2 and isinstance(matches[0][0], str) and matches[0][0].startswith("/"):
                    for url, date_str in matches:
                        full_url = self._normalize_url(url)
                        date_standard = self._parse_date(date_str)
                        if date_standard:
                            announcements.append((date_standard, full_url))
                # 如果找到匹配，跳出循环
                if announcements:
                    break

        # 如果正则都未匹配，尝试用更通用的方式：查找所有 a 标签
        if not announcements:
            # 提取所有链接和文本
            all_links = re.findall(r'<a\s+[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', html)
            for url, text in all_links:
                if "人民币汇率中间价" in text:
                    # 从文本中提取日期
                    date_match = re.search(r'(\d{4}年\d{1,2}月\d{1,2}日)', text)
                    if date_match:
                        date_str = date_match.group(1)
                        full_url = self._normalize_url(url)
                        date_standard = self._parse_date(date_str)
                        if date_standard:
                            announcements.append((date_standard, full_url))

        # 去重（按日期去重）
        seen = set()
        unique = []
        for date, url in announcements:
            if date not in seen:
                seen.add(date)
                unique.append((date, url))
        announcements = unique

        print(f"[调试] 获取到 {len(announcements)} 条公告")
        return announcements

    def _normalize_url(self, url: str) -> str:
        """补全URL"""
        if url.startswith("/"):
            return self.BASE_URL + url
        elif url.startswith("http"):
            return url
        else:
            return self.BASE_URL + "/" + url

    def _parse_date(self, date_str: str) -> Optional[str]:
        """将中文日期转为 YYYY-MM-DD"""
        try:
            dt = datetime.strptime(date_str, "%Y年%m月%d日")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    def get_exchange_rates(self, date_str: Optional[str] = None) -> Optional[Dict[str, float]]:
        """
        获取指定日期的人民币汇率中间价（返回已统一为 1人民币 = X外币）
        """
        announcements = self.get_announcement_list()
        if not announcements:
            return None

        announcements.sort(key=lambda x: x[0], reverse=True)

        if date_str is None:
            target_date, target_url = announcements[0]
        else:
            matches = [(d, u) for d, u in announcements if d == date_str]
            if not matches:
                return None
            target_date, target_url = matches[0]

        try:
            resp = self.session.get(target_url, timeout=15)
            resp.encoding = "utf-8"
            html = resp.text
        except Exception as e:
            print(f"[错误] 获取公告页面失败: {e}")
            return None

        # 提取公告文本（增强版）
        full_text = ""
        # 尝试从 <p> 或内容区域提取
        patterns = [
            r'<p[^>]*>(.*?)</p>',
            r'<div[^>]*class="content"[^>]*>(.*?)</div>',
            r'<td[^>]*>(.*?)</td>',
            r'<div[^>]*id="content"[^>]*>(.*?)</div>',
        ]
        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                clean = re.sub(r'<[^>]+>', '', match)
                clean = re.sub(r'\s+', ' ', clean).strip()
                if "人民币汇率中间价" in clean or "对人民币" in clean:
                    full_text += clean + " "

        # 如果没有提取到，直接清理整个页面文本
        if not full_text:
            html_clean = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            html_clean = re.sub(r'<style[^>]*>.*?</style>', '', html_clean, flags=re.DOTALL)
            html_clean = re.sub(r'<[^>]+>', ' ', html_clean)
            html_clean = re.sub(r'\s+', ' ', html_clean).strip()
            # 找到包含 "人民币汇率中间价" 的一段文字（前后扩展）
            idx = html_clean.find("人民币汇率中间价")
            if idx != -1:
                # 提取前后一定范围
                start = max(0, idx - 50)
                end = min(len(html_clean), idx + 800)
                full_text = html_clean[start:end]

        if not full_text:
            print("[错误] 未能提取到汇率数据文本")
            return None

        # 解析并统一为 1人民币 = X外币
        rates = self._parse_and_convert(full_text)
        return rates

    def _parse_and_convert(self, text: str) -> Dict[str, float]:
        """
        解析公告文本，将所有汇率统一为 1 人民币 = X 外币
        """
        rates = {}

        # 1) 匹配 "1外币对人民币X元"  -> 需要转换
        pattern1 = r'1([^\d]+?)对人民币([\d.]+)元'
        matches1 = re.findall(pattern1, text)
        for currency, rate_str in matches1:
            currency = currency.strip()
            try:
                rate = float(rate_str)
                rates[currency] = 1.0 / rate
            except ValueError:
                continue

        # 2) 匹配 "人民币1元对X外币"  -> 已经是所需格式
        pattern2 = r'人民币1元对([\d.]+)([^\d，。、]+?)(?:，|、|。|$)'
        matches2 = re.findall(pattern2, text)
        for rate_str, currency in matches2:
            currency = currency.strip()
            try:
                rate = float(rate_str)
                rates[currency] = rate
            except ValueError:
                continue

        # 3) 处理韩元等特殊（可能没有“元”字）
        pattern3 = r'人民币1元对([\d.]+)([^\d，。、]+?)(?:，|、|。|$)'
        matches3 = re.findall(pattern3, text)
        for rate_str, currency in matches3:
            currency = currency.strip()
            if currency not in rates:
                try:
                    rate = float(rate_str)
                    rates[currency] = rate
                except ValueError:
                    continue

        return rates


class ExchangeRateGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("人民币汇率中间价查询")
        self.root.geometry("650x550")
        self.root.resizable(True, True)

        self.extractor = PBOCExchangeRate()
        self.rates_data = None
        self.current_date = None
        self.announcements = []
        self.available_dates = []

        # --- 顶部：日期选择 ---
        frame_top = ttk.LabelFrame(root, text="选择日期", padding=10)
        frame_top.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame_top, text="日期 (YYYY-MM-DD):").grid(row=0, column=0, padx=5, pady=5, sticky="w")

        self.date_var = tk.StringVar()
        self.date_entry = ttk.Entry(frame_top, textvariable=self.date_var, width=15)
        self.date_entry.grid(row=0, column=1, padx=5, pady=5)

        # “刷新列表”按钮
        self.btn_refresh = ttk.Button(frame_top, text="刷新公告列表", command=self.refresh_announcements)
        self.btn_refresh.grid(row=0, column=2, padx=5, pady=5)

        # “最新”按钮
        self.btn_latest = ttk.Button(frame_top, text="获取最新", command=self.fetch_latest)
        self.btn_latest.grid(row=0, column=3, padx=5, pady=5)

        # “查询”按钮
        self.btn_fetch = ttk.Button(frame_top, text="查询该日汇率", command=self.fetch_selected)
        self.btn_fetch.grid(row=0, column=4, padx=5, pady=5)

        # 日期范围提示
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
        self.status_var.set("就绪，请先刷新公告列表")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", padx=10, pady=5)

        # 自动刷新列表
        self.refresh_announcements()

    def refresh_announcements(self):
        """刷新公告列表"""
        self.status_var.set("正在获取公告列表...")
        self.root.update()
        try:
            self.announcements = self.extractor.get_announcement_list()
            self.announcements.sort(key=lambda x: x[0], reverse=True)
            self.available_dates = [d for d, _ in self.announcements]

            if self.available_dates:
                self.date_var.set(self.available_dates[0])  # 设置最新日期
                self.date_info_label.config(
                    text=f"可用日期: {self.available_dates[-1]} ~ {self.available_dates[0]} (共{len(self.available_dates)}条)",
                    foreground="green"
                )
                self.btn_latest.config(state="normal")
                self.btn_fetch.config(state="normal")
                self.status_var.set(f"公告列表加载成功，最新日期: {self.available_dates[0]}")
                # 自动获取最新汇率
                self.fetch_latest()
            else:
                self.date_info_label.config(text="未获取到任何公告，请检查网络或稍后重试", foreground="red")
                self.btn_latest.config(state="disabled")
                self.btn_fetch.config(state="disabled")
                self.status_var.set("公告列表为空，请检查网络或网站是否可访问")
                messagebox.showerror("错误", "未能获取到任何公告列表。\n请检查网络连接或稍后重试。")
        except Exception as e:
            self.date_info_label.config(text="获取公告列表异常", foreground="red")
            self.status_var.set(f"异常: {str(e)}")
            messagebox.showerror("异常", str(e))

    def fetch_latest(self):
        """获取最新汇率"""
        if not self.available_dates:
            messagebox.showwarning("提示", "请先刷新公告列表")
            return
        self.status_var.set("正在获取最新汇率...")
        self.root.update()
        try:
            rates = self.extractor.get_exchange_rates()  # date_str=None 表示最新
            if rates:
                self.rates_data = rates
                self.current_date = self.available_dates[0]
                self._display_rates(rates)
                self.btn_export.config(state="normal")
                self.status_var.set(f"成功获取 {self.current_date} 的汇率")
            else:
                messagebox.showerror("错误", "获取最新汇率失败，可能页面结构已变化")
                self.status_var.set("获取失败")
        except Exception as e:
            messagebox.showerror("异常", str(e))
            self.status_var.set("出错")

    def fetch_selected(self):
        """获取指定日期的汇率"""
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
                f"没有 {date_str} 的公告数据\n可用范围: {self.available_dates[-1]} ~ {self.available_dates[0]}"
            )
            return

        self.status_var.set(f"正在获取 {date_str} 汇率...")
        self.root.update()
        try:
            rates = self.extractor.get_exchange_rates(date_str)
            if rates:
                self.rates_data = rates
                self.current_date = date_str
                self._display_rates(rates)
                self.btn_export.config(state="normal")
                self.status_var.set(f"成功获取 {date_str} 的汇率")
            else:
                messagebox.showerror("错误", f"获取 {date_str} 汇率失败，可能页面结构已变化")
                self.status_var.set("获取失败")
        except Exception as e:
            messagebox.showerror("异常", str(e))
            self.status_var.set("出错")

    def _display_rates(self, rates: Dict[str, float]):
        """在 Treeview 中显示汇率"""
        for row in self.tree.get_children():
            self.tree.delete(row)

        sorted_items = sorted(rates.items(), key=lambda x: x[0])
        for currency, rate in sorted_items:
            rate_str = f"{rate:.6f}"
            self.tree.insert("", "end", values=(currency, rate_str))

    def clear_display(self):
        """清空显示"""
        for row in self.tree.get_children():
            self.tree.delete(row)
        self.rates_data = None
        self.current_date = None
        self.btn_export.config(state="disabled")
        self.status_var.set("已清空")

    def export_excel(self):
        """导出到桌面 Excel"""
        if not self.rates_data:
            messagebox.showwarning("提示", "没有数据可导出")
            return

        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.exists(desktop):
            desktop = os.getcwd()

        if self.current_date:
            filename = f"人民币汇率_{self.current_date}.xlsx"
        else:
            filename = "人民币汇率.xlsx"

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