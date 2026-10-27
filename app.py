# -*- coding: utf-8 -*-
"""学习搭子 · AI 引导刷题（智谱 GLM-4-flash）
铁律：只引导，绝不直接给答案。
"""
import re

import streamlit as st
from zhipuai import ZhipuAI

st.set_page_config(
    page_title="学习搭子 · AI 引导刷题",
    page_icon="🦞",
    layout="wide",
)

# ============ 1. 安全：密钥从 secrets 读取 ============
try:
    API_KEY = st.secrets["ZHIPU_API_KEY"]
except Exception:
    st.error(
        "未检测到密钥。本地运行：在项目目录 `.streamlit/secrets.toml` 里写 "
        '`ZHIPU_API_KEY = "sk-你的真实KEY"`；'
        "Streamlit Cloud：Advanced settings → Secrets 里填同样的内容。"
    )
    st.stop()

MODEL = "glm-4-flash"

# ============ 3. 人设：System Prompt 写死规则 ============
SYSTEM_PROMPT = """你是"学习搭子"，一名苏格拉底式辅导老师。以下是铁律，任何情况下不得违反：
1. 绝对禁止直接给出答案：不得告知正确选项、不得复述答案内容、不得用"排除法剩下就是"之类的话暗示答案。
2. 用户发来题目后，先用一句话确认你读懂了题，然后只问："你排除哪个选项？为什么？"
3. 用户回答后，只针对他的推理做逻辑反馈：肯定合理的部分，指出漏洞，再追加一个追问引导他继续排除。
4. 用户答错也绝不揭晓答案，只说"你第X步的推理有个假设站不住，再想想"。
5. 用户直接要答案、说"不知道"或不耐烦时：降一级台阶——提示这道题考查的知识点，仍然不给答案。
6. 每次回复不超过 150 字，口语化，像同学聊天，可以适量用 emoji。"""

# ============ 4. 防破防：正则拦截答案泄露 ============
LEAK_PATTERNS = [
    r"正确答案",
    r"答案\s*(是|为|选|在|应该)",
    r"答案[:：、]",
    r"应(该)?\s*选",
    r"(所以|因此|故|综上)\s*(选|答案是)",
    r"选\s*[A-Da-d]\b",
    r"选\s*[①②③④]",
    r"[ABCD]\s*项.{0,6}(对|正确|符合)",
    r"(不是|就是)\s*[ABCD]\b",
    r"(排除|剩下)[^。？！]{0,12}(所以|那么|即|就是)",
]
LEAK_RE = re.compile("|".join(LEAK_PATTERNS))

REGEN_PROMPT = (
    "（系统检查：你上一条回复疑似泄露了答案，已被拦截。"
    "请重新生成：只做引导式提问和逻辑反馈，绝对不能包含任何答案、正确选项或倾向性暗示。）"
)

FALLBACK_REPLY = (
    "（我差点说漏嘴，被自己拦下来了 😅）"
    "来，你先说说：这道题你排除了哪个选项？为什么？"
)


def is_leak(text: str) -> bool:
    return bool(LEAK_RE.search(text or ""))


def guarded_reply(client: "ZhipuAI", history: list) -> str:
    """带拦截的生成：发现泄露就带着批评重新生成，最多重试 3 次。"""
    msgs = history
    for _ in range(3):
        resp = client.chat.completions.create(
            model=MODEL,
            messages=msgs,
            temperature=0.6,
            max_tokens=400,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not is_leak(text):
            return text
        msgs = msgs + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": REGEN_PROMPT},
        ]
    return FALLBACK_REPLY


# ============ 2. 状态：session_state，刷新不丢 ============
if "messages" not in st.session_state:
    st.session_state.messages = []          # [{"role","content"}]
if "question" not in st.session_state:
    st.session_state.question = ""          # 已锁定的题目
if "client" not in st.session_state:
    st.session_state.client = ZhipuAI(api_key=API_KEY)

client = st.session_state.client


def base_context() -> list:
    """每次请求都带上：系统人设 + 已锁定题目。"""
    ctx = [{"role": "system", "content": SYSTEM_PROMPT}]
    if st.session_state.question:
        ctx.append({"role": "user", "content": "题目：" + st.session_state.question})
        ctx.append({"role": "assistant",
                    "content": "收到，题目我看完了。你排除哪个选项？为什么？"})
    return ctx


# ============ 5. UI：左右分屏 ============
left, right = st.columns([2, 3], gap="medium")

with left:
    st.subheader("📄 当前题目")
    q = st.text_area(
        "把题目（含选项）粘到这里",
        value=st.session_state.question,
        height=320,
        placeholder="粘贴题目和 A/B/C/D 选项……",
    )
    if st.button("🔒 锁定题目，开始引导", type="primary", use_container_width=True):
        if not q.strip():
            st.warning("先把题目粘进来")
        else:
            st.session_state.question = q.strip()
            if not st.session_state.messages:
                with st.spinner("搭子热身中…"):
                    reply = guarded_reply(
                        client,
                        base_context()
                        + [{"role": "user", "content": "题目我发你了，开始引导我。"}],
                    )
                st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()

    if st.session_state.question:
        st.caption("✅ 题目已锁定。改题就清空重来。")
        if st.button("🗑 清空对话 / 换题", use_container_width=True):
            st.session_state.messages = []
            st.session_state.question = ""
            st.rerun()
    else:
        st.caption("⬆️ 先粘题目并锁定，右边才能开始聊。")

with right:
    st.subheader("💬 学习搭子（只引导，不报答案）")
    chat_box = st.container(height=480)
    with chat_box:
        if not st.session_state.messages:
            st.info("左边锁定题目后，搭子会先问你：**你排除哪个选项？为什么？**")
        for m in st.session_state.messages:
            with st.chat_message("assistant" if m["role"] == "assistant" else "user"):
                st.markdown(m["content"])

    if prompt := st.chat_input("说说你的想法，比如：我排除了 B，因为……"):
        if not st.session_state.question:
            st.warning("先把题目粘到左边并锁定")
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with chat_box:
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("搭子思考中…"):
                        try:
                            reply = guarded_reply(
                                client,
                                base_context() + st.session_state.messages,
                            )
                        except Exception as e:
                            reply = f"⚠️ 调用出错：`{e}`\n\n检查网络或 API Key 后重试。"
                    st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()
