"""
考研数学智能组卷系统 - 通用大模型 AI 智能名师答疑服务 (Clean-Room 原创实现)
支持任意兼容 OpenAI 接口规范的大模型（DeepSeek、GPT-4o、Qwen、GLM、Claude中转、Ollama 本地大模型等）
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Generator

from core.models import QuestionItem

logger = logging.getLogger(__name__)

SYSTEM_TUTOR_PROMPT = """你是一位顶尖考研数学名师，精通高等数学、线性代数与概率论全部题型与考场解法。
请为学生详细解答指定的考研数学《880》题目。

解答要求：
1. 【核心考点】：清晰点明本题考查的核心定理或解题方法。
2. 【标准答案】：明确给出最终正确答案（选择题给出选项字母如【答案：C】，填空题给出确切表达式，解答题给出最终结果）。
3. 【详细推导步骤】：逻辑严密清晰，分步书写，所有数学公式必须使用标准的 LaTeX 语法（行内公式用 $...$，独立公式用 $$...$$）。
4. 【避坑关键提醒】：结合历年考场实战经验，一针见血指出学生最容易失分、写错或忽略的隐蔽陷阱与易错点。
"""


class AITutor:
    """通用大模型 AI 智能解题助手（支持任意 OpenAI 兼容端点）"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "deepseek-chat",
    ):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        self.model = model or "deepseek-chat"
        self.endpoint = self._normalize_endpoint(base_url or os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com"))

    @staticmethod
    def _normalize_endpoint(url: str) -> str:
        url = (url or "").strip().rstrip("/")
        if not url:
            return "https://api.deepseek.com/chat/completions"
        if url.endswith("/chat/completions"):
            return url
        return f"{url}/chat/completions"

    def solve_question_stream(self, question: QuestionItem) -> Generator[str, None, None]:
        if not self.api_key:
            yield "【提示】未配置 API Key，请在侧边栏填写您的 Base URL、API Key 与 Model 名称开启 AI 智能精讲。"
            return

        options_text = ""
        if question.options:
            options_text = "\n选项：\n" + "\n".join(question.options)

        user_content = f"""【题目编号】：{question.id}
【所属章节】：{question.chapter} ({question.category.value})
【题型难度】：{question.difficulty.value} - {question.question_type.value}
【考查标签】：{", ".join(question.tags) if question.tags else "常规考点"}
【题干正文】：
{question.stem}{options_text}

请按照名师要求提供规范的解题步骤、最终答案与避坑指南。"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_TUTOR_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.2,
            "stream": True,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            req = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0]["delta"].get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
        except urllib.error.HTTPError as he:
            err_body = ""
            try:
                err_body = he.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            yield f"【API 错误】HTTP {he.code}: {he.reason}\n请求地址: `{self.endpoint}`\n模型: `{self.model}`\n{err_body}"
        except Exception as e:
            yield f"【网络异常】无法连接至大模型服务 `{self.endpoint}` ({self.model}): {e}"
