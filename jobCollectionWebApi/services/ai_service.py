from config import settings
from core.logger import sys_logger as logger
import json


class AIService:
    async def generate_career_advice(self, major: str, skills: list) -> str:
        """根据专业和技能生成职业建议"""
        if settings.AI_PROVIDER == "mock":
            return self._mock_advice(major, skills)
        
        return await self._call_llm(major, skills)
        
    def _mock_advice(self, major, skills):
        skills_str = ", ".join(skills[:5]) if skills else "相关专业技能"
        
        return f"""### 🎓 {major} 职业发展建议 (AI 模拟版)

**1. 🚀 核心职业赛道**
根据当前市场数据分析，{major} 专业毕业生在以下领域具有极高竞争力：
- **后端开发工程师**: 市场需求旺盛，重点考察 {skills_str} 等技术能力。
- **全栈开发工程师**: 建议在掌握后端基础的同时，补充 Vue/React 等前端框架知识。
- **数据应用工程师**: 结合业务场景进行数据清洗与分析。

**2. 📈 短期学习路线 (未来3个月)**
- **第1个月 (基础夯实)**: 深入理解核心编程语言的高级特性，完成至少 50 道 LeetCode 算法题。
- **第2个月 (项目实战)**: 动手开发一个完整的 Web 项目（如博客系统或电商后台），并部署上线。
- **第3个月 (面试冲刺)**: 整理“{major}”相关的面试八股文，并进行模拟面试。

**3. ✨ 简历优化亮点**
- **技能显性化**: 在简历显眼位置列出 **{skills_str}**，并标注熟练程度。
- **项目数字化**: 用“提升 50% 性能”、“减少 30% 响应时间”等数据量化项目成果。
- **拥抱开源**: 哪怕是提交一次文档修正，也是技术热情的最好证明。

*(💡 提示: 在配置文件中设置真实 AI API Key，可解锁针对您个人情况的实时深度分析)*"""

    async def get_career_navigation_report(self, major_name: str, es_stats: dict) -> str:
        """根据 ES 的真实岗位数据和特定专业生成职业病理诊断与规划报告"""
        
        system_prompt = """
你是一名面向大学生的“专家级职业规划导师”。
你的任务是根据系统提供的一份【真实的招聘市场宏观数据】以及【学生的就读专业】，为学生出具一份详尽、一针见血的《职业罗盘诊断报告》。
请保持语言干练、客观，带有洞察力，直接指出该专业在当前市场下的优劣势，并提供明确的转型或补充学习方向。

格式要求使用 Markdown：
## 🗺️ {专业名称} 的全景市场透视
## 💸 薪水天花板预估
## 🎯 核心落地行业与岗位
## ⚔️ 差距预警 (Gap Analysis)
## 🚀 行动指南
"""
        user_prompt = f"""
学生就读专业：{major_name}

=== 市场真实客观数据 (基于十万级有效招聘需求聚合) ===
{json.dumps(es_stats, ensure_ascii=False, indent=2)}
====================================

请严格基于上述客观数据（不能瞎编数据，要引用上述的行业分布和技能需求频率），为该专业的学生撰写完整的《职业罗盘诊断报告》。重点做 Gap Analysis，也就是学校教的理论同企业真实要的硬技能的差距。
"""
        return await self._call_llm_generic_text(system_prompt, user_prompt)
        
    async def _call_llm_generic_text(self, system_prompt: str, user_prompt: str) -> str:
        """通用 LLM 纯文本调用"""
        try:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {settings.AI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": settings.AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7, 
                "stream": False
            }
            url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
            timeout = aiohttp.ClientTimeout(total=90)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        return f"❌ AI 分析引擎维护中 (HTTP {resp.status})"
                    data = await resp.json()
                    return data['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"Generate report error: {e}")
            return "❌ AI 职业分析暂时不可用，请稍后再试。"

    async def _call_llm(self, major, skills):
        """调用大模型 API (OpenAI 兼容格式)"""
        try:
            import aiohttp
        except ImportError:
            return "❌ 错误: 未安装 aiohttp 库，无法调用 AI 接口。"
            
        system_prompt = "你是一名资深的互联网职业规划师和技术面试官。请根据用户的专业和市场热门技能，提供一份简练、专业的职业发展建议。输出格式为 Markdown。"
        user_prompt = f"我的专业是{major}，目前的市场热门技能是{', '.join(skills)}。请为我规划核心岗位方向、3个月学习路线及简历建议。"
        
        headers = {
            "Authorization": f"Bearer {settings.AI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": settings.AI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7,
            "stream": False
        }
        try:
            import aiohttp
            import traceback
            
            url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
            logger.info(f"AI Request URL: {url}")
            
            # 使用更长的超时时间
            timeout = aiohttp.ClientTimeout(total=60)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        logger.error(f"AI API Error: {resp.status} - {err}")
                        return f"❌ AI 服务响应错误 (HTTP {resp.status}): {err[:100]}"
                    
                    data = await resp.json()
                    if 'choices' not in data or not data['choices']:
                         return f"❌ AI 返回格式异常: {json.dumps(data)}"
                         
                    content = data['choices'][0]['message']['content']
                    return content
                    
        except Exception as e:
            logger.error(f"AI Call Failed: {str(e)}")
            traceback.print_exc() # 打印完整堆栈到控制台
            return f"❌ 调用 AI 发生异常: {str(e)}"

    async def parse_resume_text(self, text: str) -> dict:
        """解析简历文本为 JSON"""
        # if settings.AI_PROVIDER == "mock":
        #     return {
        #         "name": "模拟用户", 
        #         "education": "本科",
        #         "experience": "3年",
        #         "skills": ["Python", "Vue"],
        #         "summary": "这是模拟的简历解析结果。"
        #     }
            
        system_prompt = "你是一个专业的简历解析助手。请提取以下简历内容的关键信息，并以严格的 JSON 格式返回。不要包含任何markdown标记。"
        user_prompt = f"""
        请分析以下简历内容，并提取关键信息。返回 JSON 格式。
        字段包括：
        - name (string: 姓名)
        - phone (string: 手机号)
        - email (string: 邮箱)
        - age (number: 年龄，如果没有则估算或为null)
        - gender (string: 性别，如 "男", "女")
        - desired_position (string: 期望职位)
        - summary (string: 200字以内的个人总结/个人优势)
        - skills (list of strings: 技能列表)
        - educations (list of objects):
            - school (string: 学校名称)
            - major (string: 专业)
            - degree (string: 学历，如 "本科")
            - start_date (string: YYYY-MM-DD 格式)
            - end_date (string: YYYY-MM-DD 格式)
        - work_experiences (list of objects):
            - company (string: 公司名称)
            - position (string: 职位)
            - department (string: 部门，可选)
            - start_date (string: YYYY-MM-DD 格式)
            - end_date (string: YYYY-MM-DD 格式，至今写今天日期)
            - content (string: 工作内容描述)
        
        简历内容：
        {text[:3000]}
        """
        
        return await self._call_llm_generic(system_prompt, user_prompt)

    async def _call_llm_generic(self, system_prompt, user_prompt):
        """Generic LLM call returning JSON if possible or string"""
        try:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {settings.AI_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": settings.AI_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.1, 
                "stream": False
            }
            
            url = f"{settings.AI_BASE_URL.rstrip('/')}/chat/completions"
            timeout = aiohttp.ClientTimeout(total=60)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        return {"error": f"HTTP {resp.status}"}
                    
                    data = await resp.json()
                    content = data['choices'][0]['message']['content']
                    
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()
                    
                    try:
                        return json.loads(content)
                    except:
                        return {"summary": content} 
        except Exception as e:
            logger.error(f"AI Error: {e}")
            return {}

    async def parse_job_search_intent(self, user_query: str) -> dict:
        """解析口语化的职位搜索意图为结构化 JSON"""
        
        system_prompt = """
你是一个专业的招聘意图分析引擎。你的任务是将用户自然语言表达的求职需求，精确地转换为结构化的 JSON 数据。
无论用户的语言多么零散、口语化，你都需要运用逻辑推理能力对其进行分类和提取。
如果某个字段在用户的表述中没有提及或无法安全推断，请留空（如 null 或 []，严格按照下面的定义）。
不要输出任何 Markdown 标记或多余的文字说明，只输出原始 JSON 字符串。
"""
        
        user_prompt = f"""
请分析以下求职意图，并提取包含以下键名的 JSON 数据：
- locations (list of strings): 地点/城市。比如 "北京", "杭州"。
- keywords (list of strings): 岗位通配词、职能大类。比如 "后端开发", "产品经理"。
- skills_must_have (list of strings): 明确点名的技术栈或工具。比如 "Python", "Golang", "Figma"。
- salary_min (number或null): 最低月薪要求(单位:人民币元)。如 "2万" 记为 20000。
- salary_max (number或null): 最高月薪要求(单位:人民币元)。如 "不超过3万" 记为 30000。
- exclude_keywords (list of strings): 用户明确排斥的词汇。如 "不要外包" -> ["外包"]。
- benefits_desired (list of strings): 期望的公司福利。如 "双休", "不加班", "五险一金"。
- education (string或null): 学历要求。如 "本科" 或 "大专"。
- experience (string或null): 经验年限要求。如 "1-3年", "应届生", "5-10年"。
- industry (string或null): 行业类型。如 "互联网", "游戏行业"。

用户的求职意图原话如下：
{user_query}
"""
        
        return await self._call_llm_generic(system_prompt, user_prompt)

ai_service = AIService()
