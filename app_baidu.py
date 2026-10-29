# -*- coding: utf-8 -*-
"""学习搭子 · AI 引导刷题（百度千帆 ERNIE-Speed 版）
铁律：只引导，绝不直接给答案。
接口：https://qianfan.baidubce.com/v2/chat/completions（OpenAI 兼容）
免费模型：ernie-speed-8k / ernie-lite-8k / ernie-tiny-8k / ernie-3.5-8k
"""
import re

import httpx
import streamlit as st

st.set_page_config(
    page_title="学习搭子 · 百度文心版",
    page_icon="🐬",
    layout="wide",
)

BASE_URL = "https://qianfan.baidubce.com/v2/chat/completions"


# ============ 1. 安全：密钥优先读 secrets，没有就在页面手动填 ============
def _secret_key() -> str:
    try:
        v = st.secrets["QIANFAN_API_KEY"]
        return str(v or "").strip()
    except Exception:
        return ""


def _secret_model() -> str:
    try:
        v = st.secrets["QIANFAN_MODEL"]
        return str(v or "").strip()
    except Exception:
        return ""


SECRET_KEY = _secret_key()
DEFAULT_MODEL = _secret_model() or "ernie-speed-8k"

if "api_key" not in st.session_state:
    st.session_state.api_key = SECRET_KEY

with st.sidebar:
    st.header("🔑 密钥设置")
    st.caption(f"当前模型：{DEFAULT_MODEL}")
    if SECRET_KEY:
        st.success("已使用云端配置的密钥")
    elif st.session_state.api_key:
        st.success("✅ 密钥已就绪")
        if st.button("清除密钥"):
            st.session_state.api_key = ""
            st.rerun()
    else:
        st.warning("还没有 Key")
    st.link_button("去百度智能云取 Key", "https://console.bce.baidu.com/iam/#/iam/apikey/list")
    st.caption("Key 只存在你这台设备的这次会话里，不上传服务器。")

API_KEY = (st.session_state.get("api_key") or "").strip()

if not API_KEY:
    st.title("🐬 学习搭子 · 百度文心版")
    st.markdown("**第一次使用，请先粘贴你的百度千帆 API Key**（只在你这台设备的内存里，不上传服务器）")
    k = st.text_input(
        "千帆 API Key（bce-v3/ 开头的一长串）",
        type="password",
        placeholder="bce-v3/ALTAK-xxxxxxxx",
        key="main_key_input",
    )
    if k and k.strip():
        st.session_state.api_key = k.strip()
        st.rerun()
    with st.expander("📖 怎么拿 Key？（点开看 4 步）", expanded=False):
        st.markdown(
            "1. 打开 https://console.bce.baidu.com/iam/#/iam/apikey/list （需百度智能云账号，已实名）\n"
            "2. 点「创建 API Key」，权限勾选「千帆 ModelBuilder」\n"
            "3. 创建后点「复制」，**完整一整串**（bce-v3/ 开头）\n"
            "4. 去 https://console.bce.baidu.com/qianfan/overview → 在线服务，确认 **ernie-speed-8k** 已「免费开通」"
        )
    st.stop()

MODEL = DEFAULT_MODEL

# ============ 3. 人设：System Prompt 写死规则 ============
SYSTEM_PROMPT = """你是"学习搭子"，一名苏格拉底式辅导老师。以下是铁律，任何情况下不得违反：
1. 绝对禁止直接给出答案：不得告知正确选项、不得复述答案内容、不得用"排除法剩下就是"之类的话暗示答案。
2. 用户发来题目后，先用一句话确认你读懂了题，然后只问："你排除哪个选项？为什么？"
3. 用户回答后，只针对他的推理做逻辑反馈：肯定合理的部分，指出漏洞，再追加一个追问引导他继续排除。
4. 用户答错也绝不揭晓答案，只说"你第X步的推理有个假设站不住，再想想"。
5. 用户直接要答案、说"不知道"或不耐烦时：降一级台阶——提示这道题考查的知识点，仍然不给答案。
6. 每次回复不超过 150 字，口语化，像同学聊天，可以适量用 emoji。
7. 你只负责提问和指出逻辑漏洞，不负责陈述学科知识结论。用户的前提可能有问题时，只说"你这句话里有个前提值得再核实一下"，绝不自己下断言、也不要附和——避免把错误知识教给用户。
8. 不要重复用户已经说过的话，也不要自我矛盾；不确定的事就说"这个你回去翻一下课本第X节"。"""

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


def friendly_error(e: Exception) -> str:
    s = str(e)
    low = s.lower()
    if "401" in s or "unauthorized" in low or "invalid_iam_token" in low or "unauthenticated" in low:
        return "API Key 不对。请重新粘贴**完整的一串**（bce-v3/ 开头），或去百度智能云 IAM 确认 Key 有效。"
    if "403" in s or "forbidden" in low or "no permission" in low or "not authorized" in low:
        return "Key 有效但没权限：多半是模型没开通。去千帆控制台 → 在线服务，把 **ernie-speed-8k** 点「免费开通」再试。"
    if "404" in s or "not found" in low or "model" in low and "not" in low:
        return "模型名不对或没开通。去千帆控制台确认 **ernie-speed-8k** 已免费开通。"
    if "429" in s or "rate limit" in low or "tpm" in low or "rpm" in low:
        return "调用太频繁了（免费档有速度上限），歇 10 秒再发。"
    if "timeout" in low or "timed out" in low:
        return "网络超时了，再发一次试试。"
    if "实名" in s or "realname" in low:
        return "百度智能云账号还没实名认证，去控制台完成实名后重试。"
    return s[:220]


def chat_once(api_key: str, messages: list, temperature: float = 0.6) -> str:
    """调千帆 V2 接口（OpenAI 兼容），返回模型回复文本。"""
    resp = httpx.post(
        BASE_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 400,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def guarded_reply(api_key: str, history: list) -> str:
    """带拦截的生成：发现泄露就带着批评重新生成，最多重试 3 次。"""
    msgs = history
    for _ in range(3):
        text = chat_once(api_key, msgs)
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


def base_context() -> list:
    """每次请求都带上：系统人设 + 已锁定题目。"""
    ctx = [{"role": "system", "content": SYSTEM_PROMPT}]
    if st.session_state.question:
        ctx.append({"role": "user", "content": "题目：" + st.session_state.question})
        ctx.append({"role": "assistant",
                    "content": "收到，题目我看完了。你排除哪个选项？为什么？"})
    return ctx


def first_context() -> list:
    """首轮专用：干净上下文，避免重复开场。"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "题目：" + st.session_state.question},
    ]


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
                    try:
                        reply = guarded_reply(
                            API_KEY,
                            first_context()
                            + [{"role": "user", "content": "我开始做这道题了，请你引导我。"}],
                        )
                    except Exception as e:
                        st.session_state.question = ""
                        st.error("⚠️ " + friendly_error(e))
                        st.stop()
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
                                API_KEY,
                                base_context() + st.session_state.messages,
                            )
                        except Exception as e:
                            reply = "⚠️ " + friendly_error(e)
                    st.markdown(reply)
            st.session_state.messages.append({"role": "assistant", "content": reply})
            st.rerun()
