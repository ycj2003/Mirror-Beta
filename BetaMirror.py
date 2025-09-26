import streamlit as st
from openai import OpenAI
import time

# --- 新增的Firebase导入和初始化 ---
import firebase_admin
from firebase_admin import credentials, firestore
import json
from uuid import uuid4
import hashlib

import streamlit.components.v1 as components

# 初始化 Firebase（只会运行一次）
if not firebase_admin._apps:
    # 检查 Secrets 中是否有私钥
    if 'FIREBASE_PRIVATE_KEY' in st.secrets:
        try:
            # 从 Streamlit Secrets 中构建私钥字典
            private_key_dict = {
                "type": st.secrets["FIREBASE_TYPE"],
                "project_id": st.secrets["FIREBASE_PROJECT_ID"],
                "private_key_id": st.secrets["FIREBASE_PRIVATE_KEY_ID"],
                "private_key": st.secrets["FIREBASE_PRIVATE_KEY"].replace('\\n', '\n'), # 关键：处理换行符
                "client_email": st.secrets["FIREBASE_CLIENT_EMAIL"],
                "client_id": st.secrets["FIREBASE_CLIENT_ID"],
                "auth_uri": st.secrets["FIREBASE_AUTH_URI"],
                "token_uri": st.secrets["FIREBASE_TOKEN_URI"],
                "auth_provider_x509_cert_url": st.secrets["FIREBASE_AUTH_PROVIDER_CERT_URL"],
                "client_x509_cert_url": st.secrets["FIREBASE_CLIENT_CERT_URL"]
            }
            # 使用字典初始化认证
            cred = credentials.Certificate(private_key_dict)
            firebase_admin.initialize_app(cred)
            st.session_state.db_initialized = True
        except Exception as e:
            st.sidebar.error(f"Firebase 初始化失败: {e}")
            st.session_state.db_initialized = False
    else:
        st.session_state.db_initialized = False
else:
    st.session_state.db_initialized = True

# 获取 Firestore 客户端
if st.session_state.get('db_initialized'):
    db = firestore.client()
else:
    db = None

# ---------------------------- 页面配置 ----------------------------
st.set_page_config(
    page_title="镜子",
    page_icon="🪞",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ---------------------------- 简化的用户身份管理 ----------------------------
def get_user_id():
    """生成稳定的用户ID"""
    if 'user_id' not in st.session_state:
        # 使用简单但稳定的方法生成用户ID
        browser_info = {
            'timestamp': str(int(time.time() / 3600)),  # 按小时分组，提供一定稳定性
            'session_hash': str(abs(hash(str(st.session_state))))[:8]
        }
        
        user_hash = hashlib.md5(
            f"{browser_info['timestamp']}_{browser_info['session_hash']}".encode()
        ).hexdigest()[:12]
        
        st.session_state.user_id = f"user_{user_hash}"
    
    return st.session_state.user_id

# ---------------------------- 简化的会话管理 ----------------------------
def get_session_id():
    """获取或创建会话ID"""
    user_id = get_user_id()
    
    # 1. 优先使用URL参数中的会话ID
    if 'session_id' in st.query_params:
        session_id = st.query_params['session_id']
        # 简单验证：会话ID应该包含用户标识
        if user_id[:8] in session_id:  # 使用用户ID的前8位进行验证
            st.session_state.current_session_id = session_id
            return session_id
    
    # 2. 检查session_state中是否已有会话ID
    if hasattr(st.session_state, 'current_session_id') and st.session_state.current_session_id:
        if user_id[:8] in st.session_state.current_session_id:
            return st.session_state.current_session_id
    
    # 3. 创建新会话ID
    timestamp = int(time.time())
    random_part = str(uuid4())[:6]
    new_session_id = f"{user_id}_{timestamp}_{random_part}"
    
    st.session_state.current_session_id = new_session_id
    st.query_params['session_id'] = new_session_id
    
    return new_session_id

# ---------------------------- Firebase操作函数 ----------------------------
def save_conversation(session_id, messages):
    """保存对话到Firebase"""
    if not st.session_state.get('db_initialized') or not db:
        return False, "Firebase未初始化"
    
    try:
        # 只保存用户和助手的消息，跳过系统消息
        messages_to_save = [msg for msg in messages if msg.get('role') in ['user', 'assistant']]
        
        doc_ref = db.collection("conversations").document(session_id)
        doc_ref.set({
            'messages': messages_to_save,
            'last_updated': firestore.SERVER_TIMESTAMP,
            'user_id': get_user_id(),
            'message_count': len(messages_to_save)
        })
        return True, "保存成功"
    except Exception as e:
        return False, f"保存失败: {str(e)}"

def load_conversation(session_id):
    """从Firebase加载对话"""
    if not st.session_state.get('db_initialized') or not db:
        return None, "Firebase未初始化"
    
    try:
        doc_ref = db.collection("conversations").document(session_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            messages = data.get('messages', [])
            
            # 验证消息是否属于当前用户
            stored_user_id = data.get('user_id')
            current_user_id = get_user_id()
            
            if stored_user_id and current_user_id[:8] in stored_user_id:
                return messages, "加载成功"
            else:
                return None, "用户验证失败"
        else:
            return None, "未找到会话记录"
    except Exception as e:
        return None, f"加载失败: {str(e)}"

def get_user_sessions():
    """获取当前用户的会话列表"""
    if not st.session_state.get('db_initialized') or not db:
        return []
    
    try:
        user_id = get_user_id()
        current_session = get_session_id()
        
        # 查询最近的会话
        docs = db.collection("conversations").order_by('last_updated', direction=firestore.Query.DESCENDING).limit(10).stream()
        
        user_sessions = []
        for doc in docs:
            doc_data = doc.to_dict()
            session_id = doc.id
            stored_user_id = doc_data.get('user_id', '')
            
            # 检查是否属于当前用户，且不是当前会话
            if (user_id[:8] in stored_user_id and 
                session_id != current_session and 
                doc_data.get('messages')):
                
                messages = doc_data.get('messages', [])
                last_message = ""
                if messages:
                    last_message = messages[-1].get('content', '')[:50]
                    if len(messages[-1].get('content', '')) > 50:
                        last_message += "..."
                
                user_sessions.append({
                    'id': session_id,
                    'preview': last_message,
                    'time': doc_data.get('last_updated'),
                    'count': len(messages)
                })
        
        return user_sessions
    except Exception as e:
        st.sidebar.error(f"获取会话列表失败: {e}")
        return []

# ---------------------------- 自定义CSS ----------------------------
st.markdown("""
<style>
    .stChatMessage {
        padding: 1rem;
    }
    /* 用户消息气泡样式 */
    [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-user"] {
        background-color: #4e79a7 !important;
    }
    /* AI消息气泡样式 */
    [data-testid="stChatMessage"] [data-testid="chatAvatarIcon-assistant"] {
        background-color: #f28e2c !important;
    }
    /* 主标题样式 */
    .main-title {
        text-align: center;
        color: #4e79a7;
        margin-bottom: 0.5rem;
    }
    /* 副标题样式 */
    .subtitle {
        text-align: center;
        color: #6b6b6b;
        font-style: italic;
        margin-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# ==================== 配置区域 ====================
BACKGROUND_SETTING = """
你是一个对话者，是一个会进行阶段性整合的苏格拉底式提问者。
无休止的提问会让用户感到压力很大，要做阶段性整合，比如在用户感到困惑时，或至多在5次左右的提问后，陪用户一起梳理思考的过程。
提问时，减少对抽象概念的提问，要询问对具体事物的看法，描述对具体事情的感受等等，让用户容易回答。
多用具象化的东西、具体的感受来表述，你的服务对象是全人类，要让所有人都能听懂。
需要用户进行联想时，要让用户联想他们熟悉的东西，在一开始尽量避免让用户联想可能会感觉不舒服的场景，更不要对此进行追问。
你的语气要温和、坚定，让用户感到友善且被尊重，用词要注意分寸，夸张的用词会给用户压力。
盒子是一切可能影响认知的因素，包括"固有思维模式"、"自我认同的标签"、"社会规训"、"未经审视的恐惧"等。但是在与用户沟通时，不要提"盒子"，用户听不懂。
影响好坏的评判标准完全交给用户，你是一面镜子，你不是上帝。
你是纯粹的镜子，不要引导，不要引导。
如果我要叫停你，我会以"叫停。"开始，这时中断与用户的对话，我们探讨如何调整。
"""

TASK_DIRECTIVE = """
你的第一个目标是，让用户认出盒子。
你的第二个目标是，让用户有"原来这是我认知上的问题，那如果我从盒子外考虑问题，事情是否会变得不一样？"的想法。
你的第三个目标是，让用户觉得"维持现状"或者"我为什么不试试呢？"，选择权是用户的，但让用户产生这个想法是很大的成功。
提问的方式：1、聚焦于"定义"与"行为"的联结；2、邀请进行"思维实验"；3、聚焦于"盒子"的边界和特性。每次可以根据具体情况从以上三点进行选择。
"""

OPENING_TEMPLATE = "你好，我是一面镜子。在这里思考，亦看见你思维本身的模样。"+"\n"+"在你心里，有没有一个话题、一种感觉或一件事，一想到就会感觉不舒服或者被卡住？或者你会反复去想，但又不太确定从哪里开始梳理的？如果你愿意，可以和我聊聊任何事。"

SYSTEM_PROMPT = BACKGROUND_SETTING + "\n" + TASK_DIRECTIVE

# ---------------------------- 初始化会话状态 ----------------------------
if "api_key_configured" not in st.session_state:
    st.session_state.api_key_configured = False
if "client" not in st.session_state:
    st.session_state.client = None
if "db_initialized" not in st.session_state:
    st.session_state.db_initialized = False

# 获取当前会话信息
current_user_id = get_user_id()
current_session_id = get_session_id()

# 初始化或加载对话历史
if "messages" not in st.session_state:
    # 尝试从Firebase加载对话历史
    loaded_messages, load_message = load_conversation(current_session_id)
    
    if loaded_messages:
        # 成功加载历史记录
        st.session_state.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ] + loaded_messages
        st.sidebar.success(f"✅ {load_message} (共{len(loaded_messages)}条消息)")
    else:
        # 创建新对话
        st.session_state.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "assistant", "content": OPENING_TEMPLATE}
        ]
        if load_message != "未找到会话记录":
            st.sidebar.info(f"ℹ️ {load_message}")

# API密钥设置
if 'DEEPSEEK_API_KEY' in st.secrets and not st.session_state.api_key_configured:
    try:
        client = OpenAI(api_key=st.secrets['DEEPSEEK_API_KEY'], base_url="https://api.deepseek.com")
        # 简单测试
        test_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "测试"}],
            max_tokens=5
        )
        st.session_state.api_key_configured = True
        st.session_state.client = client
    except Exception as e:
        st.session_state.secrets_error = str(e)
        st.session_state.api_key_configured = False

# ---------------------------- 侧边栏 ----------------------------
with st.sidebar:
    st.header("🛠️ 设置")
    
    # 显示调试信息
    st.caption(f"👤 用户: {current_user_id[-8:]}...")
    st.caption(f"💬 会话: {current_session_id[-12:]}...")
    
    # API密钥配置
    if hasattr(st.session_state, 'secrets_error'):
        st.error(f"预配置API密钥错误: {st.session_state.secrets_error}")
    
    if not st.session_state.api_key_configured:
        api_key = st.text_input("Deepseek API密钥", type="password")
        
        if api_key:
            try:
                client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
                test_response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "测试"}],
                    max_tokens=5
                )
                st.success("API密钥有效!")
                st.session_state.api_key_configured = True
                st.session_state.client = client
            except Exception as e:
                st.error(f"API密钥错误: {str(e)}")
    else:
        st.success("✅ API密钥已配置")
    
    st.divider()
    
    # 会话管理
    st.subheader("📁 会话管理")
    
    # 显示历史会话
    user_sessions = get_user_sessions()
    if user_sessions:
        st.write("**历史对话:**")
        for i, session in enumerate(user_sessions[:5]):
            time_str = "未知"
            if session['time']:
                try:
                    time_str = session['time'].strftime("%m-%d %H:%M")
                except:
                    time_str = "最近"
            
            button_label = f"📂 {time_str} ({session['count']}条)"
            if st.button(button_label, key=f"load_session_{i}"):
                # 切换到选中的会话
                st.session_state.current_session_id = session['id']
                st.query_params['session_id'] = session['id']
                
                # 清除当前消息以强制重新加载
                if 'messages' in st.session_state:
                    del st.session_state['messages']
                
                st.success(f"正在加载会话...")
                st.rerun()
            
            # 显示预览
            if session['preview']:
                st.caption(f"💭 {session['preview']}")
    else:
        st.caption("暂无历史对话")
    
    # 新建会话按钮
    if st.button("🆕 新建会话"):
        # 生成新会话ID
        new_session_id = f"{current_user_id}_{int(time.time())}_{str(uuid4())[:6]}"
        
        # 更新会话状态
        st.session_state.current_session_id = new_session_id
        st.query_params['session_id'] = new_session_id
        
        # 清除消息历史
        if 'messages' in st.session_state:
            del st.session_state['messages']
        
        st.success("正在创建新会话...")
        st.rerun()
    
    st.divider()
    st.caption("💡 对话会自动保存到云端")

# ---------------------------- 主界面 ----------------------------
st.markdown('<h1 class="main-title">🪞 镜子</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">明镜止水。</p>', unsafe_allow_html=True)

# 显示聊天记录（跳过系统消息）
for message in st.session_state.messages[1:]:
    avatar = "🪞" if message["role"] == "assistant" else "👤"
    with st.chat_message(message["role"], avatar=avatar):
        st.markdown(message["content"])

# 处理用户输入
if prompt := st.chat_input("请输入您的想法..."):
    if not st.session_state.api_key_configured:
        st.error("❌ 请先配置API密钥")
        st.stop()
    
    # 添加用户消息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    
    # 检查叫停指令
    if prompt.startswith("叫停。"):
        with st.chat_message("assistant", avatar="🪞"):
            st.info("已收到叫停指令。请告诉我需要如何调整？")
        st.stop()
    
    # 生成AI回复
    with st.chat_message("assistant", avatar="🪞"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            # API调用
            api_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *st.session_state.messages[1:]
            ]
            
            stream = st.session_state.client.chat.completions.create(
                model="deepseek-chat",
                messages=api_messages,
                stream=True,
                temperature=0.1
            )
            
            # 流式输出
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    full_response += chunk.choices[0].delta.content
                    message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
            
        except Exception as e:
            st.error(f"❌ API调用出错: {str(e)}")
            full_response = "抱歉，镜子暂时模糊了，请稍后再试。"
            message_placeholder.markdown(full_response)
    
    # 添加AI回复到历史
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    
    # 保存对话到Firebase
    success, message = save_conversation(current_session_id, st.session_state.messages)
    if success:
        st.sidebar.success("💾 对话已自动保存")
    else:
        st.sidebar.error(f"💾 保存失败: {message}")
