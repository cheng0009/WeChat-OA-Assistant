import httpx
import re
from typing import Optional
from app.config import settings
from app.writing_skills import WritingSkillDef


SYSTEM_PROMPT_FULL = """你正在以「老成」的身份写一篇公众号长文，发布到微信公众平台。

老成是一个70后自媒体从业者，运营着公众号「70后教你做自媒体」。他的文章风格一句话概括：
**"凡事懂得看本质，用最通俗平实富有人情味的语言聊一聊打动他的事和观点。"**

## 核心要求
- **全文控制在 1800-2000 字**，要有观点有态度，避免空话套话
- 精选 2-3 条最火、与普通人最相关的新闻来写
- 每条新闻要包含**原文摘录**和**来源引用**，展现老成认真阅读了原文
- 像朋友聊天，有观点有温度
- **自称"老成"全文最多出现1-2次**，不要反复提

## 文章结构
【开头】一句话切入，迅速建立兴趣，可以引用原文
【正文】每条新闻：说清楚发生了什么 + 引用原文出处 + 老成的看法和评论
【结尾】一句总结或行动建议，带个人态度

## 输出格式
**第一行是完整文章标题（用 # 开头），要求 54-64 字，公众号爆款风格，抓眼球。**
**第二行是短标题（用 ## 短标题：开头），要求 20 字以内，用于封面图和贴图。**
正文中可以用 ## 做小标题分段，段落之间空一行。不要用 ** 和 ###。"""


STICKER_SYSTEM_PROMPT = """你正在以「老成」的身份，将一篇公众号长文浓缩为贴图版短文，用于微信图片配文。

## 要求
- 浓缩为 **800-1000 字**
- 保留核心观点、金句和态度
- 去掉原文引用的出处，只留观点
- 一样要有开头、正文、结尾的结构
- 语气保持老成风格：通俗、有人情味、有态度
- **自称"老成"全文最多出现1次**
- **段落之间只空一行，不要多个空行**

## 输出格式
只输出纯文字，分段，段落之间只空一行。不要标题。"""


class DeepSeekGenerator:
    def __init__(self):
        self.api_key = settings.deepseek_api_key
        self.base_url = settings.deepseek_base_url.rstrip("/")
        self.model = settings.deepseek_model

    async def _call_api(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096, temperature: float = 0.8) -> Optional[str]:
        if not self.api_key:
            return None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def generate_article(self, news_data: dict, skill: Optional[WritingSkillDef] = None) -> Optional[dict]:
        items = news_data.get("items", [])
        daily = news_data.get("daily")

        if not items and not daily:
            return None

        news_text = self._format_news_for_prompt(items, daily)

        persona = skill.persona if skill else "老成"
        system_prompt = skill.system_prompt if skill else SYSTEM_PROMPT_FULL

        user_prompt = f"""素材如下（精选 2-3 条最火、最贴近普通人的来写，要引用原文出处和摘录）：

{news_text}

要求：
- 第一行：完整文章标题（# 开头，54-64 字，爆款风格）
- 第二行：短标题（## 短标题：开头，20 字以内，用于封面图）
- 全文 1800-2000 字
- 口语化，像{persona}在跟读者聊天
- 每条新闻要适当引用原文摘录"""
        recent = news_data.get("recent_topics")
        if recent:
            user_prompt += "\n\n近期已写过以下主题，请避免重复：\n" + "\n".join(f"- {t}" for t in recent)

        raw = await self._call_api(system_prompt, user_prompt, max_tokens=8192)
        if not raw:
            return None

        title, body, viral_title = self._parse_article(raw)
        summary = (body.replace("\n", "")[:120] + "…") if len(body) > 120 else body

        article = {
            "title": title,
            "viral_title": viral_title or title,
            "summary": summary,
            "content": body,
        }

        # Step 2: Quality enhancement (if skill provides style guide or checklist)
        enhanced = False
        if skill and (skill.style_guide or skill.quality_checklist):
            enhanced_raw = await self._enhance_article(raw, skill)
            if enhanced_raw:
                enh_title, enh_body, enh_viral = self._parse_article(enhanced_raw)
                if enh_title and enh_body:
                    article["title"] = enh_title
                    article["viral_title"] = enh_viral or enh_title
                    article["content"] = enh_body
                    article["summary"] = (enh_body.replace("\n", "")[:120] + "…") if len(enh_body) > 120 else enh_body
                    enhanced = True

        article["enhanced"] = enhanced
        return article

    async def _enhance_article(self, raw_draft: str, skill: WritingSkillDef) -> Optional[str]:
        """Post-generation quality pass using the skill's style guide and checklist."""
        style_section = f"""## 风格指南
{skill.style_guide}
""" if skill.style_guide else ""

        checklist_section = f"""## 质量检查清单（务必逐项检查修正）
{skill.quality_checklist}
""" if skill.quality_checklist else ""

        system_prompt = f"""你是一个文章质量编辑。请严格按照以下标准对文章进行精修，修正所有不符合要求的地方。

{style_section}{checklist_section}
## 修改规则
- **保持原标题和短标题完全不变**
- 修正所有不符合风格的表述
- 替换禁区词汇
- 只输出精修后的完整文章，不要额外解释"""

        user_prompt = f"""请精修以下文章（保持标题和短标题不变）：

{raw_draft}"""

        raw = await self._call_api(system_prompt, user_prompt, max_tokens=8192, temperature=0.5)
        return raw

    async def generate_sticker(self, long_article: str, skill: Optional[WritingSkillDef] = None) -> str:
        """Condense long article (~2000 chars) to sticker version (max 1000 chars)."""
        persona = skill.persona if skill else "老成"
        sticker_prompt = skill.sticker_prompt if skill else STICKER_SYSTEM_PROMPT

        user_prompt = f"""将以下{persona}的公众号长文浓缩为 800-1000 字的贴图版短文：

{long_article[:3000]}

要求：
- 严格控制在 1000 字以内，不能超出
- 保留核心观点和金句
- 去掉原文出处引用
- 保持口语化和态度"""
        raw = await self._call_api(sticker_prompt, user_prompt, max_tokens=4096, temperature=0.7)
        if not raw:
            return long_article[:1000].rsplit("\n", 1)[0]
        result = raw.strip()
        # Hard limit: truncate at last sentence boundary within 1000 chars
        if len(result) > 1000:
            cut = result[:1000]
            last_end = max(cut.rfind("。"), cut.rfind("！"), cut.rfind("？"), cut.rfind("\n"))
            result = result[:last_end + 1] if last_end > 100 else result[:1000]
        return result

    def _parse_article(self, raw: str) -> tuple:
        lines = raw.strip().split("\n")
        title = "AI 圈今天发生了什么"
        viral_title = ""
        body_lines = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# ") and not stripped.startswith("## "):
                title = stripped.lstrip("# ").strip()
            elif stripped.startswith("## 短标题：") or stripped.startswith("## 短标题:"):
                viral_title = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
            elif stripped.startswith("短标题：") or stripped.startswith("短标题:"):
                viral_title = stripped.split("：", 1)[-1].split(":", 1)[-1].strip()
            else:
                body_lines.append(line)

        body = "\n".join(body_lines).strip()
        if not viral_title:
            viral_title = title[:20]
        return title, body, viral_title

    def _format_news_for_prompt(self, items: list, daily: Optional[dict]) -> str:
        parts = []
        if daily:
            lead = daily.get("lead")
            if lead and lead.get("leadParagraph"):
                parts.append(lead["leadParagraph"])
            sections = daily.get("sections", [])
            for section in sections:
                for item in section.get("items", []):
                    t = item.get("title", "")
                    s = item.get("sourceName", "")
                    summary = item.get("summary", "")
                    parts.append(f"- {t}（{s}）")
                    if summary:
                        parts.append(f"  {summary}")

        for item in items:
            cat = item.get("category", "")
            cat_label = {"ai-models": "模型", "ai-products": "产品", "industry": "行业", "paper": "论文", "tip": "技巧"}.get(cat, "")
            source = item.get("source", "")
            title = item.get("title", "")
            summary = item.get("summary", "")
            parts.append(f"[{cat_label}] {title} — {source}")
            if summary:
                parts.append(f"  {summary}")

        return "\n".join(parts)

    async def generate_viral_title(self, article_body: str) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是一个公众号爆款标题专家。根据文章内容，生成1个20字以内的标题，要让人忍不住点开。只输出标题本身。"},
                {"role": "user", "content": f"文章：\n\n{article_body[:1500]}"},
            ],
            "temperature": 0.9,
            "max_tokens": 100,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
