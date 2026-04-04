"""
README 更新器 - 从 RSS feeds 获取内容并更新 README 标记区域
最小实现 - 通过 TDD 测试
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict
import urllib.request


def replace_section(content: str, section_name: str, new_content: str) -> str:
    """
    替换 README 中指定 section 标记之间的内容
    
    Args:
        content: 原始 README 内容
        section_name: section 名称（例如 "now-building"）
        new_content: 新内容
    
    Returns:
        更新后的内容
    
    Raises:
        ValueError: 当找不到指定 section 时
    """
    start_marker = f"<!--START_SECTION:{section_name}-->"
    end_marker = f"<!--END_SECTION:{section_name}-->"
    
    # 检查标记是否存在
    if start_marker not in content or end_marker not in content:
        raise ValueError(f"Section '{section_name}' not found in content")
    
    # 使用正则替换标记之间的内容
    pattern = f"({re.escape(start_marker)}).*?({re.escape(end_marker)})"
    replacement = f"\\1\n{new_content}\n\\2"
    
    result = re.sub(pattern, replacement, content, flags=re.DOTALL)
    return result


def parse_rss_feed(xml_content: str) -> List[Dict[str, str]]:
    """
    解析 RSS feed XML
    
    Args:
        xml_content: RSS XML 字符串
    
    Returns:
        包含 title, link, pubDate 的字典列表
    
    Raises:
        ET.ParseError: XML 格式错误时
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise Exception(f"Invalid XML: {e}")
    
    items = []
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        date_elem = item.find("pubDate")
        
        items.append({
            "title": title_elem.text if title_elem is not None else "",
            "link": link_elem.text if link_elem is not None else "",
            "pubDate": date_elem.text if date_elem is not None else "",
        })
    
    return items


def format_items_to_markdown(items: List[Dict[str, str]], max_items: int = 5) -> str:
    """
    将 RSS items 转换为 Markdown 列表
    
    Args:
        items: RSS item 字典列表
        max_items: 最大条目数
    
    Returns:
        Markdown 格式的字符串
    """
    limited_items = items[:max_items]
    lines = []
    
    for item in limited_items:
        title = item.get("title", "")
        link = item.get("link", "")
        if title and link:
            lines.append(f"- [{title}]({link})")
    
    return "\n".join(lines)


def fetch_rss_from_url(url: str) -> str:
    """
    从 URL 获取 RSS XML（真实网络请求）
    
    Args:
        url: RSS feed URL
    
    Returns:
        XML 字符串
    """
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.read().decode('utf-8')


def update_readme(
    readme_path: Path,
    rss_url: str,
    section_name: str = "feeds",
    max_items: int = 5
) -> None:
    """
    更新 README 文件的指定 section
    
    Args:
        readme_path: README.md 文件路径
        rss_url: RSS feed URL
        section_name: section 标记名
        max_items: 最大显示条目数
    """
    # 1. 读取 README
    content = readme_path.read_text(encoding='utf-8')
    
    # 2. 获取并解析 RSS
    xml_content = fetch_rss_from_url(rss_url)
    items = parse_rss_feed(xml_content)
    
    # 3. 格式化为 Markdown
    new_content = format_items_to_markdown(items, max_items)
    
    # 4. 替换 section
    updated_content = replace_section(content, section_name, new_content)
    
    # 5. 写回文件
    readme_path.write_text(updated_content, encoding='utf-8')


if __name__ == "__main__":
    # 示例用法
    readme = Path("README.md")
    rss_url = "https://rsshub.231590.xyz/github/releases/itgoyo/obsidian-copilot"
    
    update_readme(readme, rss_url, section_name="now-building", max_items=3)
    print("✅ README updated successfully")
