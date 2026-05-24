# AI Financial Research System

## 项目简介
自动化 AI 金融研究系统，自动获取股票数据、分析财务指标、生成图表和 PDF 报告。

## 功能
- 自动获取股票财务数据（yfinance）
- 生成收入、利润率、PE、PB 对比图表
- 自动生成 PDF 研究报告
- 新闻情绪分析

## 项目结构
- main.py — 主程序入口
- financials.py — 财务数据获取
- charts.py — 图表生成
- news.py — 新闻获取
- pdf_generator.py — PDF 生成
- config.py — 配置文件

## 安装依赖
pip install -r requirements.txt

## 运行
python main.py
