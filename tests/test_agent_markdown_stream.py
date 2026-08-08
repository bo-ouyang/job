import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "jobCollectionWebApi"))

from agent.markdown_stream import chunk_markdown


def assert_lossless_bounded_chunks(markdown, *, max_chars=32):
    chunks = chunk_markdown(markdown, max_chars=max_chars)
    assert "".join(chunks) == markdown
    assert all(chunk.strip() and len(chunk) <= max_chars for chunk in chunks)
    return chunks


def test_chunk_markdown_prefers_chinese_sentence_boundaries():
    markdown = "第一段说明市场情况。第二句说明岗位要求。第三句给出行动建议。"

    chunks = assert_lossless_bounded_chunks(markdown, max_chars=15)

    assert chunks[0].endswith("。")
    assert len(chunks) >= 3


def test_chunk_markdown_prefers_english_sentence_boundaries():
    markdown = "Python demand is rising. Django remains common. Build one project now."

    chunks = assert_lossless_bounded_chunks(markdown, max_chars=28)

    assert chunks[0].rstrip().endswith(".")


def test_chunk_markdown_preserves_emoji_and_unicode_text():
    markdown = "方向 🚀：后端开发。行动 ✅：完成部署。Résumé 与 数据分析并重。"

    chunks = assert_lossless_bounded_chunks(markdown, max_chars=14)

    assert "🚀" in "".join(chunks)
    assert "✅" in "".join(chunks)


def test_chunk_markdown_hard_wraps_a_long_paragraph_losslessly():
    markdown = "超长技能说明" * 80

    chunks = assert_lossless_bounded_chunks(markdown, max_chars=31)

    assert len(chunks) > 2


def test_chunk_markdown_keeps_list_lines_as_preferred_units():
    markdown = "## 下一步\n\n- 学习 Django 并完成项目\n- 掌握 Redis 缓存模式\n- 完成 Linux 部署"

    chunks = assert_lossless_bounded_chunks(markdown, max_chars=30)

    assert any(chunk.endswith("\n") for chunk in chunks[:-1])


def test_chunk_markdown_returns_one_chunk_for_a_short_answer():
    assert chunk_markdown("简短回答。", max_chars=256) == ["简短回答。"]


def test_chunk_markdown_returns_no_chunks_for_empty_or_blank_answer():
    assert chunk_markdown("", max_chars=256) == []
    assert chunk_markdown("   \n", max_chars=256) == []


def test_chunk_markdown_rejects_a_non_positive_limit():
    try:
        chunk_markdown("answer", max_chars=0)
    except ValueError as exc:
        assert "max_chars" in str(exc)
    else:
        raise AssertionError("expected max_chars validation")
