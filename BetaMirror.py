import streamlit as st
from openai import OpenAI
import time

# --- 新增的Firebase导入和初始化 ---
import firebase_admin
from firebase_admin import credentials, firestore
import json
from uuid import uuid4

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

# ---------------------------- 用户身份管理 ----------------------------
def get_user_id():
    """获取唯一的用户身份标识"""
    # 使用浏览器fingerprint作为用户标识
    if 'browser_user_id' not in st.session_state:
        # 生成基于时间和随机数的用户ID
        st.session_state.browser_user_id = f"browser_{int(time.time())}_{str(uuid4())[:12]}"
        
        # 尝试从localStorage获取已存储的用户ID
        get_user_id_script = f"""
        <script>
        var storedUserId = localStorage.getItem('mirror_user_id');
        if (storedUserId && storedUserId !== 'null') {{
            // 如果找到已存储的用户ID，通过自定义事件发送给Streamlit
            window.dispatchEvent(new CustomEvent('userIdFound', {{
                detail: {{ userId: storedUserId }}
            }});
            
            // 同时尝试通过postMessage发送（兼容性）
            window.parent.postMessage({{
                type: 'USER_ID_FOUND',
                userId: storedUserId
            }}, '*');
        }} else {{
            // 没找到，存储新生成的用户ID
            localStorage.setItem('mirror_user_id', '{st.session_state.browser_user_id}');
        }}
        </script>
        """
        components.html(get_user_id_script, height=0)
    
    return st.session_state.browser_user_id

# ---------------------------- 会话 ID 管理（添加用户隔离） ----------------------------
def get_current_session_id():
    """获取当前会话ID - 绑定到特定用户"""
    
    # 首先确保有用户ID
    user_id = get_user_id()
    
    # 1. 如果session_state中已有ID，直接使用
    if 'user_session_id' in st.session_state and st.session_state.user_session_id:
        return st.session_state.user_session_id
    
    # 2. 尝试从URL参数获取
    if 'session_id' in st.query_params:
        session_id = st.query_params['session_id']
        # 验证这个session_id是否属于当前用户
        if session_id.startswith(user_id[:8]):  # 简单验证
            st.session_state.user_session_id = session_id
            
            # 后台同步到localStorage
            sync_script = f"""
            <script>
            try {{
                localStorage.setItem('mirror_session_id', '{session_id}');
            }} catch(e) {{
                console.log('localStorage不可用:', e);
            }}
            </script>
            """
            components.html(sync_script, height=0)
            
            return session_id
    
    # 3. 创建新的用户专属会话ID
    new_session_id = f"{user_id}_{int(time.time())}_{str(uuid4())[:6]}"
    st.session_state.user_session_id = new_session_id
    
    # 更新URL参数
    st.query_params['session_id'] = new_session_id
    
    # 同步到localStorage
    sync_script = f"""
    <script>
    try {{
        localStorage.setItem('mirror_session_id', '{new_session_id}');
    }} catch(e) {{
        console.log('localStorage不可用:', e);
    }}
    </script>
    """
    components.html(sync_script, height=0)
    
    return new_session_id

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

# ==================== 配置区域 (您的设计模块) ====================
# 1. 背景设定 (AI的"宪法")
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

# 2. 目标任务 (AI的"行动纲领")
TASK_DIRECTIVE = """
你的第一个目标是，让用户认出盒子。
你的第二个目标是，让用户有"原来这是我认知上的问题，那如果我从盒子外考虑问题，事情是否会变得不一样？"的想法。
你的第三个目标是，让用户觉得"维持现状"或者"我为什么不试试呢？"，选择权是用户的，但让用户产生这个想法是很大的成功。
提问的方式：1、聚焦于"定义"与"行为"的联结；2、邀请进行"思维实验"；3、聚焦于"盒子"的边界和特性。每次可以根据具体情况从以上三点进行选择。
"""

# 3. 第一句话模板 (AI的"启动界面")
OPENING_TEMPLATE = "你好，我是一面镜子。在这里思考，亦看见你思维本身的模样。"+"\n"+"在你心里，有没有一个话题、一种感觉或一件事，一想到就会感觉不舒服或者被卡住？或者你会反复去想，但又不太确定从哪里开始梳理的？如果你愿意，可以和我聊聊任何事。"

# 组装系统提示词
SYSTEM_PROMPT = BACKGROUND_SETTING + "\n" + TASK_DIRECTIVE
# ==================== 配置结束 ====================

# ---------------------------- 初始化所有会话状态 ----------------------------
# 基础状态初始化
if "api_key_configured" not in st.session_state:
    st.session_state.api_key_configured = False
if "client" not in st.session_state:
    st.session_state.client = None
if "db_initialized" not in st.session_state:
    st.session_state.db_initialized = False
if "secrets_error" not in st.session_state:
    st.session_state.secrets_error = None

# **关键修复：统一的会话ID管理**
user_id = get_user_id()
current_session_id = get_current_session_id()

# 初始化或加载对话历史
if "messages" not in st.session_state:
    loaded_history = False
    
    # 尝试从Firebase加载历史对话
    if st.session_state.db_initialized and db:
        try:
            doc_ref = db.collection("conversations").document(current_session_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                history = data.get('history', [])
                if history:  # 只有当历史记录不为空时才加载
                    st.session_state.messages = [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        *history
                    ]
                    loaded_history = True
                    st.sidebar.success("已从存档恢复对话历史！")
        except Exception as e:
            st.sidebar.warning(f"读取存档失败: {e}")
    
    # 如果没有加载到历史记录，创建新对话
    if not loaded_history:
        st.session_state.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "assistant", "content": OPENING_TEMPLATE}
        ]

# ------------------------------API密钥设置--------------------------------
# 确保每次运行时都检查 Secrets
if 'DEEPSEEK_API_KEY' in st.secrets and not st.session_state.api_key_configured:
    try:
        client = OpenAI(api_key=st.secrets['DEEPSEEK_API_KEY'], base_url="https://api.deepseek.com")
        # 简单测试密钥是否有效
        test_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "测试"}],
            max_tokens=5
        )
        st.session_state.api_key_configured = True
        st.session_state.client = client
        # 成功配置后，不需要显示错误信息
    except Exception as e:
        # 只在 session_state 中记录错误，不直接显示
        st.session_state.secrets_error = str(e)
        st.session_state.api_key_configured = False

# ---------------------------- 侧边栏设置 ----------------------------
with st.sidebar:
    st.header("设置")
    
    # 显示当前会话ID（调试用）
    st.caption(f"当前会话: {current_session_id[:12]}...")
    
    # **会话恢复功能**
    st.subheader("📁 会话管理")
    
    # 检查是否有可恢复的会话
    if st.session_state.get('db_initialized') and db:
        # 尝试从localStorage获取上一个会话ID
        get_last_session_script = """
        <script>
        var lastSessionId = localStorage.getItem('mirror_session_id');
        if (lastSessionId && lastSessionId !== window.location.search.split('session_id=')[1]) {
            // 如果localStorage中的ID与当前URL中的不同，说明可能需要恢复
            window.parent.postMessage({
                type: 'LAST_SESSION_ID',
                sessionId: lastSessionId
            }, '*');
        }
        </script>
        """
        components.html(get_last_session_script, height=0)
        
        # 检查Firebase中是否有其他会话（仅限当前用户）
        try:
            # 只查询属于当前用户的会话记录
            user_prefix = user_id[:12]  # 使用用户ID前缀进行过滤
            
            # 查询所有会话，然后在Python中过滤（因为Firestore的前缀查询限制）
            docs = db.collection("conversations").order_by('last_updated', direction=firestore.Query.DESCENDING).limit(20).stream()
            recent_sessions = []
            
            for doc in docs:
                doc_data = doc.to_dict()
                session_id = doc.id
                
                # 严格检查：只显示属于当前用户的会话
                if (session_id.startswith(user_prefix) and 
                    session_id != current_session_id and 
                    doc_data.get('history')):
                    
                    # 获取最后一条消息的时间和内容预览
                    last_updated = doc_data.get('last_updated')
                    history = doc_data.get('history', [])
                    if history:
                        last_message = history[-1].get('content', '')[:50] + '...' if len(history[-1].get('content', '')) > 50 else history[-1].get('content', '')
                        recent_sessions.append({
                            'id': session_id,
                            'preview': last_message,
                            'time': last_updated,
                            'message_count': len(history)
                        })
            
            if recent_sessions:
                st.write("🔄 **您的历史对话记录**")
                
                # 显示当前用户的会话列表
                for i, session in enumerate(recent_sessions[:3]):  # 只显示最近3个
                    time_str = "未知时间"
                    if session['time']:
                        try:
                            time_str = session['time'].strftime("%m-%d %H:%M")
                        except:
                            time_str = "最近"
                    
                    session_preview = f"会话 {session['id'][-8:]}... ({session['message_count']}条消息)"
                    if session['preview']:
                        session_preview += f"\n最后消息: {session['preview']}"
                    
                    if st.button(f"📂 恢复会话 ({time_str})", key=f"restore_{i}", help=session_preview):
                        # 再次验证会话属于当前用户
                        if session['id'].startswith(user_prefix):
                            # 恢复选中的会话
                            st.session_state.user_session_id = session['id']
                            st.query_params['session_id'] = session['id']
                            
                            # 清除当前消息
                            if 'messages' in st.session_state:
                                del st.session_state['messages']
                            
                            # 更新localStorage
                            update_storage_script = f"""
                            <script>
                            localStorage.setItem('mirror_session_id', '{session['id']}');
                            window.location.reload();
                            </script>
                            """
                            components.html(update_storage_script, height=0)
                            
                            st.success(f"正在恢复会话 {session['id'][-8:]}...")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("安全验证失败：无法访问该会话")
                
                st.caption("💡 提示：只显示您自己的对话记录")
            else:
                st.caption("暂无您的历史对话记录")
                
        except Exception as e:
            st.caption(f"检查历史会话时出错: {e}")
    
    st.divider()
    if hasattr(st.session_state, 'secrets_error') and st.session_state.secrets_error:
        st.error(f"预配置API密钥错误: {st.session_state.secrets_error}")
    
    # 只有在没有配置云端密钥时才显示输入框
    if not st.session_state.api_key_configured:
        api_key = st.text_input("Deepseek API密钥", type="password", help="请输入您的Deepseek API密钥")
        
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
                # 清除可能的错误信息
                if hasattr(st.session_state, 'secrets_error'):
                    del st.session_state.secrets_error
            except Exception as e:
                st.error(f"API密钥无效或出错: {str(e)}")
                st.session_state.api_key_configured = False
    else:
        st.success("已使用预配置的API密钥")
    
    st.divider()
    st.caption("""
    **使用说明:**
    1. 如需输入API密钥，请在左侧输入
    2. 开始与认知镜子对话
    3. 如果需要中断AI的当前回应，可以刷新页面
    """)
    
    # **简化新对话功能**
    if st.button("🔄 创建新会话"):
        # 生成新的用户专属会话ID
        new_session_id = f"{user_id}_{int(time.time())}_{str(uuid4())[:6]}"
        
        # 清除Firebase中的旧数据（静默处理）
        if st.session_state.db_initialized and db:
            try:
                doc_ref = db.collection("conversations").document(current_session_id)
                doc_ref.delete()
            except:
                pass  # 静默处理错误
        
        # 清除本地状态
        if 'messages' in st.session_state:
            del st.session_state['messages']
        
        # 更新会话ID
        st.session_state.user_session_id = new_session_id
        st.query_params['session_id'] = new_session_id
        
        # 更新localStorage并刷新页面
        refresh_script = f"""
        <script>
        localStorage.setItem('mirror_session_id', '{new_session_id}');
        window.location.reload();
        </script>
        """
        components.html(refresh_script, height=0)
        
        st.success("正在创建新会话...")
        time.sleep(1)
        st.rerun()

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
        st.error("请先在侧边栏配置有效的API密钥")
        st.stop()
    
    # 添加用户消息到历史并显示
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)
    
    # 检查是否为叫停指令
    if prompt.startswith("叫停。"):
        with st.chat_message("assistant", avatar="🪞"):
            st.info("已收到叫停指令。请告诉我需要如何调整？")
        st.stop()
    
    # 准备API调用
    with st.chat_message("assistant", avatar="🪞"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            # 调用API（使用流式输出）
            api_messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                *st.session_state.messages[1:]  # 跳过第一条系统消息，保留对话历史
            ]
            
            stream = st.session_state.client.chat.completions.create(
                model="deepseek-chat",
                messages=api_messages,
                stream=True,
                temperature=0.1
            )
            
            # 流式输出处理
            for chunk in stream:
                if chunk.choices[0].delta.content is not None:
                    chunk_content = chunk.choices[0].delta.content
                    full_response += chunk_content
                    message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.markdown(full_response)
            
        except Exception as e:
            st.error(f"API调用出错: {str(e)}")
            full_response = "抱歉，镜子暂时模糊了，请稍后再试。"
            message_placeholder.markdown(full_response)
    
    # 添加AI回复到历史
    st.session_state.messages.append({"role": "assistant", "content": full_response})

    # **修复：使用正确的会话ID保存数据**
    if st.session_state.get('db_initialized') and db:
        try:
            # 只保存实际对话消息，跳过系统提示词
            messages_to_save = st.session_state.messages[1:]
            doc_ref = db.collection("conversations").document(current_session_id)
            doc_ref.set({
                'history': messages_to_save,
                'last_updated': firestore.SERVER_TIMESTAMP,
                'session_id': current_session_id  # 添加会话ID用于调试
            })
        except Exception as e:
            st.sidebar.warning(f"对话存档失败: {e}")
