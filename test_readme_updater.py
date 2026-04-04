"""
TDD 测试：RSS feeds 更新 README 脚本
遵循最小化测试策略 - 只测试核心逻辑，避免网络依赖
"""
import pytest
from pathlib import Path


# ============== 测试 1: 标记替换逻辑 ==============

def test_replace_content_between_markers():
    """测试替换 <!-- START/END --> 标记之间的内容"""
    # Given: README 内容包含标记
    original = """# Title
<!--START_SECTION:test-->
old content
to be replaced
<!--END_SECTION:test-->
## Footer"""
    
    new_content = "new content line 1\nnew content line 2"
    
    # When: 替换标记之间的内容
    from readme_updater import replace_section
    result = replace_section(original, "test", new_content)
    
    # Then: 只替换标记之间的部分
    expected = """# Title
<!--START_SECTION:test-->
new content line 1
new content line 2
<!--END_SECTION:test-->
## Footer"""
    assert result == expected


def test_replace_section_preserves_other_content():
    """测试替换时不影响其他内容"""
    original = """<!--START_SECTION:a-->
content a
<!--END_SECTION:a-->
<!--START_SECTION:b-->
content b
<!--END_SECTION:b-->"""
    
    from readme_updater import replace_section
    result = replace_section(original, "a", "NEW A")
    
    assert "NEW A" in result
    assert "content b" in result  # section b 不受影响
    assert "content a" not in result


def test_replace_section_raises_if_marker_not_found():
    """测试标记不存在时抛出错误"""
    content = "# No markers here"
    
    from readme_updater import replace_section
    with pytest.raises(ValueError, match="Section.*not found"):
        replace_section(content, "nonexistent", "new")


# ============== 测试 2: RSS 解析器 (mock 数据) ==============

@pytest.fixture
def mock_rss_xml():
    """模拟 RSS feed XML（避免网络请求）"""
    return """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Latest Release v1.2.3</title>
      <link>https://github.com/user/repo/releases/v1.2.3</link>
      <pubDate>Fri, 03 Apr 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Older Release v1.2.2</title>
      <link>https://github.com/user/repo/releases/v1.2.2</link>
      <pubDate>Mon, 01 Apr 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


def test_parse_rss_feed(mock_rss_xml):
    """测试从 XML 解析 RSS items"""
    from readme_updater import parse_rss_feed
    
    # When: 解析 mock XML
    items = parse_rss_feed(mock_rss_xml)
    
    # Then: 返回正确的数据结构
    assert len(items) == 2
    assert items[0]["title"] == "Latest Release v1.2.3"
    assert items[0]["link"] == "https://github.com/user/repo/releases/v1.2.3"
    assert "2026" in items[0]["pubDate"]


def test_parse_rss_feed_empty():
    """测试空 RSS feed"""
    empty_xml = """<?xml version="1.0"?><rss><channel></channel></rss>"""
    
    from readme_updater import parse_rss_feed
    items = parse_rss_feed(empty_xml)
    
    assert items == []


def test_parse_rss_feed_invalid_xml():
    """测试无效 XML"""
    invalid = "not xml at all"
    
    from readme_updater import parse_rss_feed
    with pytest.raises(Exception):  # 具体异常类型由实现决定
        parse_rss_feed(invalid)


# ============== 测试 3: 内容格式化 ==============

def test_format_items_to_markdown():
    """测试将 RSS items 转换为 Markdown 列表"""
    items = [
        {"title": "Release v1.0", "link": "https://example.com/v1.0"},
        {"title": "Bug fix", "link": "https://example.com/fix"},
    ]
    
    from readme_updater import format_items_to_markdown
    result = format_items_to_markdown(items, max_items=2)
    
    # Then: 生成 Markdown 链接
    assert "- [Release v1.0](https://example.com/v1.0)" in result
    assert "- [Bug fix](https://example.com/fix)" in result


def test_format_items_respects_max_limit():
    """测试限制最大条目数"""
    items = [{"title": f"Item {i}", "link": f"link{i}"} for i in range(10)]
    
    from readme_updater import format_items_to_markdown
    result = format_items_to_markdown(items, max_items=3)
    
    lines = [line for line in result.split("\n") if line.strip()]
    assert len(lines) == 3


# ============== 集成测试 ==============

def test_update_readme_file(tmp_path, monkeypatch):
    """集成测试：完整流程（使用临时文件和 mock）"""
    # Given: 创建临时 README
    readme_path = tmp_path / "README.md"
    readme_path.write_text("""# Test
<!--START_SECTION:feeds-->
old
<!--END_SECTION:feeds-->
## End""")
    
    # Mock RSS 获取函数（避免真实网络请求）
    def mock_fetch_rss(url):
        return """<?xml version="1.0"?>
<rss><channel>
  <item><title>Test Item</title><link>http://test.com</link></item>
</channel></rss>"""
    
    from readme_updater import update_readme
    monkeypatch.setattr("readme_updater.fetch_rss_from_url", mock_fetch_rss)
    
    # When: 执行更新
    update_readme(readme_path, "http://fake-rss.com", section_name="feeds")
    
    # Then: 文件被正确更新
    updated = readme_path.read_text()
    assert "Test Item" in updated
    assert "old" not in updated
    assert "<!--START_SECTION:feeds-->" in updated


# ============== 边界情况测试 ==============

def test_empty_new_content():
    """测试空内容替换"""
    original = """<!--START_SECTION:x-->
content
<!--END_SECTION:x-->"""
    
    from readme_updater import replace_section
    result = replace_section(original, "x", "")
    
    # 应保留标记，但内容为空
    assert "<!--START_SECTION:x-->" in result
    assert "<!--END_SECTION:x-->" in result


def test_special_characters_in_content():
    """测试特殊字符处理"""
    original = """<!--START_SECTION:test-->
old
<!--END_SECTION:test-->"""
    
    # 包含特殊字符的新内容
    new_content = """- [Test & <Demo>](https://example.com?a=1&b=2)
  "Quotes" and 'apostrophes'"""
    
    from readme_updater import replace_section
    result = replace_section(original, "test", new_content)
    
    # 特殊字符应正确保留
    assert "&" in result
    assert "<Demo>" in result
    assert '"Quotes"' in result
