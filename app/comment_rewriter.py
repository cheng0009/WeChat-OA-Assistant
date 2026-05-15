"""Comment rewriting engine: rewrites a single article with AI commentary."""
from typing import Optional
from app.generator import DeepSeekGenerator, SYSTEM_PROMPT_FULL
from app.models import Channel


COMMENT_REWRITE_PROMPT = """你正在以「{persona}」的身份，对下面这篇微信文章进行评论改写。

## 原文信息
标题：{title}
来源：{source}
摘要：{summary}
{content_section}

## 要求
1. 保留原文核心事实和信息
2. 在关键段落后面加入 {persona} 的评论和观点
3. 风格：通俗、有态度、有人情味，像是朋友在聊天
4. 字数 1200-1500 字
5. 开头要抓眼球，让普通人也想点开看
6. 结尾要有总结态度

## 输出格式
第一行是标题（用 # 开头），正文中用 ## 做小标题分段，段落之间空一行。不要用 ** 和 ###。"""


class CommentRewriter:
    """Rewrites a single news item into a commentary article."""

    def __init__(self, channel: Optional[Channel] = None, generator: Optional[DeepSeekGenerator] = None):
        self.channel = channel
        self.generator = generator or DeepSeekGenerator()

    async def rewrite_item(self, item: dict) -> Optional[dict]:
        """Rewrite a single article item. Returns {title, content, summary} or None."""
        title = item.get("title", "")
        source = item.get("source", "微信")
        summary = item.get("summary", "")
        content = item.get("content", "")

        persona = "老成"
        base_prompt = COMMENT_REWRITE_PROMPT

        # If channel has custom prompt, use its persona name
        if self.channel and self.channel.writer_prompt:
            base_prompt = self.channel.writer_prompt
            # Extract persona name from first line if possible
            first_line = base_prompt.strip().split("\n")[0]
            if "「" in first_line and "」" in first_line:
                persona = first_line.split("「")[1].split("」")[0]

        content_section = ""
        if content:
            content_section = f"原文内容：\n{content[:2000]}"

        user_prompt = COMMENT_REWRITE_PROMPT.format(
            persona=persona,
            title=title,
            source=source,
            summary=summary[:500],
            content_section=content_section,
        )

        system = self.channel.writer_prompt if (self.channel and self.channel.writer_prompt) else SYSTEM_PROMPT_FULL

        raw = await self.generator._call_api(system, user_prompt, max_tokens=8192)
        if not raw:
            return None

        parsed_title, body, viral_title = self.generator._parse_article(raw)
        summary_out = (body.replace("\n", "")[:120] + "…") if len(body) > 120 else body

        return {
            "title": parsed_title or f"老成锐评：{title}",
            "viral_title": viral_title or parsed_title,
            "summary": summary_out,
            "content": body,
        }
