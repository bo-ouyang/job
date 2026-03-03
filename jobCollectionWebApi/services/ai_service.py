import hashlib
from typing import TypedDict, List, Dict, Any, Optional, Type
from pydantic import BaseModel, Field
from config import settings
from core.logger import sys_logger as logger
from core.circuit_breaker import ai_circuit_breaker, CircuitBreakerOpen
from common.databases.RedisManager import redis_manager
from core.metrics import ai_calls_total, ai_call_duration, ai_cache_hits
import json
import time


class CareerAdviceGraphState(TypedDict, total=False):
    major: str
    skills: List[str]
    market_evidence: Dict[str, Any]
    evidence_summary: str
    profile_summary: str
    gap_analysis: str
    advice_markdown: str


class AIService:
    _career_advice_graph = None

    @staticmethod
    def get_ai_cache_key(prefix: str, payload: dict) -> str:
        """
        Generate a stable cache key for AI results.
        
        Args:
            prefix (str): 缓存键的业务前缀，例如 "career_advice" 或 "career_compass"。
            payload (dict): 用户输入的请求参数载荷，用于生成 MD5 摘要校验。
            
        Returns:
            str: 拼接完成的 Redis 缓存键，格式如 "ai:career_advice:c4ca4238a0b923820dcc509a6f75849b"。
        """
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return f"ai:{prefix}:{hashlib.md5(serialized.encode()).hexdigest()}"

    async def generate_career_advice(
        self,
        major: str,
        skills: list,
        engine: str = "auto",
        market_context: Dict[str, Any] = None,
    ) -> str:
        """
        生成职业规划诊断建议
        【核心架构：结果级 AI 缓存】
        因为大量同专业 (Major) + 同技能 (Skills) 的请求会得到非常类似的高级汇总答案。
        通过计算用户输入参数的 MD5/Hash 值，我们在实际调用 OpenAI/DeepSeek 前
        先从 Redis 捞出缓存。如果有则以 1毫秒 的速度返回，极大程度为您节省了 
        API Rate limit 额度与计费成本。
        
        Args:
            major (str): 用户填报的就读专业或当前身份，例如 "计算机科学与技术"
            skills (list): 用户的擅长技能数组，例如 ["Python", "Vue3", "Redis"]
            engine (str, optional): 使用的大模型引擎选择策略 ("auto", "classic", "langgraph")。默认 "auto"。
            market_context (Dict[str, Any], optional): 结合专业与技能预查出来的行业数据上下文，防幻觉使用。默认 None。
            
        Returns:
            str: AI 规划师输出的 Markdown 格式建议。如发生熔断异常，返回友好的 ❌ 错误提示。
        """
        # ── Result-level cache ──
        cache_key = self.get_ai_cache_key("career_advice", {
            "major": major, "skills": sorted(skills or []), "engine": engine,
        })
        cached = await redis_manager.get_cache(cache_key)
        if cached is not None:
            logger.debug(f"AI career_advice cache HIT: {cache_key}")
            # Prometheus 监控：统计拦截了多少没被真正打到大模型的请求
            ai_cache_hits.labels(feature="career_advice").inc()
            return cached

        selected_engine = (engine or "auto").lower()
        if selected_engine not in {"auto", "classic", "langgraph"}:
            selected_engine = "auto"

        use_langgraph = (
            selected_engine == "langgraph"
            or (selected_engine == "auto" and settings.AI_LANGGRAPH_ENABLED)
        )
        if use_langgraph:
            graph_result = await self.generate_career_advice_langgraph(
                major,
                skills,
                market_context=market_context,
            )
            if graph_result:
                await redis_manager.set_cache(cache_key, graph_result, expire=86400)
                return graph_result
            logger.warning("LangGraph advice returned empty output, fallback to classic.")

        if settings.AI_PROVIDER == "mock":
            return self._mock_advice(major, skills)

        result = await self._call_llm(major, skills)
        # Only cache successful (non-error) responses
        if isinstance(result, str) and not result.strip().startswith("❌"):
            await redis_manager.set_cache(cache_key, result, expire=86400)
        return result

    async def generate_career_advice_langgraph(
        self,
        major: str,
        skills: list,
        market_context: Dict[str, Any] = None,
    ) -> str:
        """
        使用 LangGraph 多环节智能体工作流 (Agentic Workflow) 深度生成职业建议。
        将原本一次性“生成”任务，拆解为多个子节点：(获取行情 -> 总结候选人 -> 寻找差距 -> 生成落地计划)。
        
        Args:
            major (str): 就读专业
            skills (list): 拥有的技能列表
            market_context (Dict[str, Any], optional): 市场行情客观大盘作为证据锚点。默认 None。
            
        Returns:
            str: 经复杂思考链输出的高质量建议文本。
        """
        try:
            workflow = self._get_career_advice_graph()
        except Exception as exc:
            logger.warning(f"LangGraph unavailable, fallback to classic: {exc}")
            return ""

        initial_state: CareerAdviceGraphState = {
            "major": major,
            "skills": list(skills or [])[:12],
        }
        if market_context:
            initial_state["market_evidence"] = self._normalize_market_evidence(market_context)
        try:
            result = await workflow.ainvoke(initial_state)
            advice = result.get("advice_markdown", "")
            if isinstance(advice, str):
                return advice.strip()
            return str(advice)
        except Exception as exc:
            logger.error(f"LangGraph advice flow failed: {exc}")
            return ""

    def _get_career_advice_graph(self):
        if self._career_advice_graph is not None:
            return self._career_advice_graph
        self._career_advice_graph = self._build_career_advice_graph()
        return self._career_advice_graph

    def _build_career_advice_graph(self):
        from langgraph.graph import END, StateGraph

        graph = StateGraph(CareerAdviceGraphState)
        graph.add_node("retrieve_market_evidence", self._graph_retrieve_market_evidence)
        graph.add_node("summarize_profile", self._graph_summarize_profile)
        graph.add_node("analyze_gap", self._graph_analyze_gap)
        graph.add_node("compose_advice", self._graph_compose_advice)
        graph.set_entry_point("retrieve_market_evidence")
        graph.add_edge("retrieve_market_evidence", "summarize_profile")
        graph.add_edge("summarize_profile", "analyze_gap")
        graph.add_edge("analyze_gap", "compose_advice")
        graph.add_edge("compose_advice", END)
        return graph.compile()

    def _normalize_market_evidence(self, market_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        【优化策略：Token 上下文瘦身 (Context Optimization)】
        从真实 ES 里拉出的聚合数据往往非常庞杂，容易导致模型陷入干扰，且增加昂贵 Token 花销。
        此函数将庞杂字典规范化，仅提取最具价值的市场特征（Top10 技能，Top6 薪资带和行业）。
        
        Args:
            market_context (Dict[str, Any]): ES 聚合查询直接返回的原始大对象。
            
        Returns:
            Dict[str, Any]: 精简、清洗后的市场证据上下文，确保大模型吸收不超载。
        """
        if not isinstance(market_context, dict):
            return {}

        stats = market_context.get("stats")
        if not isinstance(stats, dict):
            stats = {}
        skills = market_context.get("skills")
        if not isinstance(skills, list):
            skills = []

        top_skills = []
        for item in skills[:10]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                value = int(item.get("value", 0))
            except Exception:
                value = 0
            top_skills.append({"name": name, "value": value})

        salary_ranges = []
        for item in stats.get("salary", [])[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                value = int(item.get("value", 0))
            except Exception:
                value = 0
            salary_ranges.append({"name": name, "value": value})

        top_industries = []
        for item in stats.get("industries", [])[:6]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                value = int(item.get("value", 0))
            except Exception:
                value = 0
            top_industries.append({"name": name, "value": value})

        try:
            total_jobs = int(stats.get("total_jobs", 0))
        except Exception:
            total_jobs = 0

        query = str(market_context.get("query", "")).strip()
        return {
            "query": query,
            "total_jobs": total_jobs,
            "salary_ranges": salary_ranges,
            "top_industries": top_industries,
            "top_skills": top_skills,
        }

    async def _build_market_evidence_for_advice(
        self,
        major: str,
        skills: List[str],
    ) -> Dict[str, Any]:
        query = (major or "").strip()
        if not query:
            query = str((skills or [""])[0]).strip()
        if not query:
            return {}

        try:
            from services.analysis_service import analysis_service

            stats = await analysis_service.get_job_stats(keyword=query)
            cloud = await analysis_service.get_skill_cloud_stats(keyword=query, limit=10)
            return self._normalize_market_evidence(
                {
                    "query": query,
                    "stats": stats,
                    "skills": cloud,
                }
            )
        except Exception as exc:
            logger.warning(f"Failed to build market evidence for advice: {exc}")
            return {}

    async def _graph_retrieve_market_evidence(
        self,
        state: CareerAdviceGraphState,
    ) -> CareerAdviceGraphState:
        evidence = state.get("market_evidence") or {}
        if not evidence:
            evidence = await self._build_market_evidence_for_advice(
                major=state.get("major", ""),
                skills=state.get("skills", []),
            )
        evidence = self._normalize_market_evidence(evidence)

        if not evidence:
            return {
                "market_evidence": {},
                "evidence_summary": "No reliable market evidence available.",
            }

        evidence_summary = json.dumps(evidence, ensure_ascii=False)
        if len(evidence_summary) > 1600:
            evidence_summary = evidence_summary[:1600] + "..."

        return {
            "market_evidence": evidence,
            "evidence_summary": evidence_summary,
        }

    async def _graph_summarize_profile(
        self,
        state: CareerAdviceGraphState,
    ) -> CareerAdviceGraphState:
        major = state.get("major", "")
        skills = state.get("skills", [])
        evidence_summary = state.get("evidence_summary", "")
        skill_text = ", ".join(skills[:8]) if skills else "No explicit skills provided."

        system_prompt = (
            "You are a career analyst. Summarize the candidate profile in 4-6 concise sentences."
        )
        user_prompt = (
            f"Major: {major}\n"
            f"Skills: {skill_text}\n"
            f"Market evidence: {evidence_summary}\n"
            "Output a concise profile summary that can be used for downstream gap analysis."
        )
        profile_summary = await self._call_llm_with_langchain(system_prompt, user_prompt)
        return {"profile_summary": profile_summary}

    async def _graph_analyze_gap(
        self,
        state: CareerAdviceGraphState,
    ) -> CareerAdviceGraphState:
        major = state.get("major", "")
        skills = state.get("skills", [])
        profile_summary = state.get("profile_summary", "")
        evidence_summary = state.get("evidence_summary", "")
        skill_text = ", ".join(skills[:12]) if skills else "No explicit skills provided."

        system_prompt = (
            "You are a senior recruiter. Output a practical skills gap analysis for entry-level hiring."
        )
        user_prompt = (
            f"Major: {major}\n"
            f"Known skills: {skill_text}\n"
            f"Profile summary: {profile_summary}\n"
            f"Market evidence: {evidence_summary}\n"
            "Return 5 bullet points with: current strength, likely gap, and high-impact action."
        )
        gap_analysis = await self._call_llm_with_langchain(system_prompt, user_prompt)
        return {"gap_analysis": gap_analysis}

    async def _graph_compose_advice(
        self,
        state: CareerAdviceGraphState,
    ) -> CareerAdviceGraphState:
        major = state.get("major", "")
        skills = state.get("skills", [])
        profile_summary = state.get("profile_summary", "")
        gap_analysis = state.get("gap_analysis", "")
        evidence_summary = state.get("evidence_summary", "")
        skill_text = ", ".join(skills[:12]) if skills else "No explicit skills provided."

        system_prompt = (
            "You are an expert career coach. Produce actionable, realistic advice in Markdown."
        )
        user_prompt = (
            f"Major: {major}\n"
            f"Skills: {skill_text}\n"
            f"Profile summary: {profile_summary}\n"
            f"Gap analysis: {gap_analysis}\n\n"
            f"Market evidence JSON: {evidence_summary}\n\n"
            "Structure your response with sections:\n"
            "1) Recommended job tracks\n"
            "2) 90-day learning plan\n"
            "3) Resume optimization checklist\n"
            "4) Interview preparation priorities\n"
        )
        advice_markdown = await self._call_llm_with_langchain(system_prompt, user_prompt)
        return {"advice_markdown": advice_markdown}

    async def _call_llm_with_langchain(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = None,
    ) -> str:
        """
        基于 LangChain 封装的通用 LLM 核心交互通道。
        内置容错提取和异步断路器保护。
        
        Args:
            system_prompt (str): 赋予大模型的人设或核心动作系统提示词 (例如 "你是一名资深面试官...")。
            user_prompt (str): 用户交互层携带实际上下文片段的数据提示词。
            temperature (float, optional): 温度参数(影响答复发散性)。不填则取自配置 Default。
            
        Returns:
            str: LLM 的返回文本；若大模型返回异常结构（数组/对象），会经过清洗合并成文本返回。
        """
        async def _inner():
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI

            if temperature is None:
                temp = settings.AI_LANGCHAIN_TEMPERATURE
            else:
                temp = temperature

            base_url = settings.AI_BASE_URL.rstrip("/")
            timeout = settings.AI_LANGCHAIN_TIMEOUT_SECONDS
            llm_kwargs: Dict[str, Any] = {
                "model": settings.AI_MODEL,
                "api_key": settings.AI_API_KEY,
                "temperature": temp,
                "timeout": timeout,
            }

            # Keep compatibility across langchain-openai versions.
            try:
                llm = ChatOpenAI(**llm_kwargs, base_url=base_url)
            except TypeError:
                llm = ChatOpenAI(**llm_kwargs, openai_api_base=base_url)

            response = await llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                chunks = []
                for item in content:
                    if isinstance(item, str):
                        chunks.append(item)
                    elif isinstance(item, dict) and "text" in item:
                        chunks.append(str(item["text"]))
                    else:
                        chunks.append(str(item))
                return "\n".join(chunks)
            return str(content)

        # Wrap with circuit breaker 
        # 【核心架构：第三方 API 熔断器保护 (Circuit Breaker)】
        # 由于外网调用（如 OpenAI、DeepSeek）极不可控（超时、封号、宕机），
        # 我们用 `ai_circuit_breaker.call` 将请求包裹。一旦内部抛出异常（如 HTTP Error/Timeout）连续超过 5 次，
        # 熔断器会从 CLOSED（健康）立马切换为 OPEN（断开）。
        # 在接下来 60 秒（降级冷却期）内，所有流经这里的请求不再苦苦等待超时，而是立刻直接抛出 CircuitBreakerOpen。
        # 此举彻底避免了由于大模型端点堵塞，引发雪崩进而耗光整台服务器性能的灾难事故。
        start_time = time.time()
        try:
            result = await ai_circuit_breaker.call(_inner)
            duration = time.time() - start_time
            # 记录接口调用耗时
            ai_call_duration.labels(method="langchain").observe(duration)
            ai_calls_total.labels(method="langchain", status="success").inc()
            return result
        except CircuitBreakerOpen as e:
            # 【优雅降级处理】: 通知用户服务暂不可用，而非返回恐怖的 500 服务器错误页面
            ai_calls_total.labels(method="langchain", status="circuit_open").inc()
            logger.warning(f"Circuit breaker open for LangChain call: {e}")
            return "❌ AI 服务暂时不可用（熔断保护中），请稍后再试。"
        except Exception as e:
            ai_calls_total.labels(method="langchain", status="failure").inc()
            logger.error(f"LangChain call failed: {e}")
            return "❌ AI 服务请求失败，请稍后再试。"
        
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
        """
        【职业罗盘核心：客观数据加持的诊断报告】
        根据 Elasticsearch 处理出来海量招聘数据的真实面貌，交由大语言模型
        生成一份带有强烈事实支撑依据、不偏离市场轨道的求职行动指南。
        
        Args:
            major_name (str): 进行大盘检索分析的初始锚点（专业）。
            es_stats (dict): 该专业相关的 ES 宏观聚合数据 (薪资分布、热门行业分布、经验要求倒置规律)。
            
        Returns:
            str: 生成带有薪水天花板预估、Gap分析警告信息的职业罗盘报告 (Markdown)。
        """
        # ── Result-level cache (12h) ──
        stats_hash = hashlib.md5(json.dumps(es_stats, sort_keys=True, default=str).encode()).hexdigest()
        cache_key = self.get_ai_cache_key("career_compass", {
            "major": major_name,
            "stats_hash": stats_hash,
        })
        cached = await redis_manager.get_cache(cache_key)
        if cached is not None:
            logger.info(f"AI career_compass cache HIT: {cache_key}")
            ai_cache_hits.labels(feature="career_compass").inc()
            return cached

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
        result = await self._call_llm_with_langchain(system_prompt, user_prompt)
        if isinstance(result, str) and not result.strip().startswith("❌"):
            await redis_manager.set_cache(cache_key, result, expire=43200)  # 12h
        return result

    async def _call_llm(self, major, skills):
        """
        调用大模型 API (直连底层)。
        已重构：统一收束为 `_call_llm_with_langchain` 以复用全局 LangChain 设置及熔断监控。
        
        Args:
            major (str): 需要投递获取建议的专业名称。
            skills (list): 需要投递评估的技能矩阵。
            
        Returns:
            str: 成功获取的规划文本。受到外层断路器安全兜底。
        """
        system_prompt = "你是一名资深的互联网职业规划师和技术面试官。请根据用户的专业和市场热门技能，提供一份简练、专业的职业发展建议。输出格式为 Markdown。"
        user_prompt = f"我的专业是{major}，目前的市场热门技能是{', '.join(skills)}。请为我规划核心岗位方向、3个月学习路线及简历建议。"
        return await self._call_llm_with_langchain(system_prompt, user_prompt)

    async def parse_resume_text(self, text: str) -> dict:
        """
        简历的自动化提取与重构：结构化输出范例 (Structured Prompting)
        将 PDF 解析器抽出来的非结构化、带有空行乱码的简历纯文本，重塑为严格的 JSON 视图对象，
        以便能够直接与 Postgres ORM 对象建立 Mapping 后安全持久化。
        
        Args:
            text (str): 用户上传简历中所能 OCR 或 PdfPlumber 解析出来的文字部分。
            
        Returns:
            dict: 提取包含姓名、教育背调数组、工作履历数组的高规整度数据结构。
        """
        class Education(BaseModel):
            school: str = Field(description="学校名称")
            major: str = Field(description="专业")
            degree: str = Field(description="学历，如 '本科'")
            start_date: str = Field(description="YYYY-MM-DD 格式")
            end_date: str = Field(description="YYYY-MM-DD 格式")

        class WorkExperience(BaseModel):
            company: str = Field(description="公司名称")
            position: str = Field(description="职位")
            department: Optional[str] = Field(default=None, description="部门，可选")
            start_date: str = Field(description="YYYY-MM-DD 格式")
            end_date: str = Field(description="YYYY-MM-DD 格式，至今写今天日期")
            content: str = Field(description="工作内容描述")

        class ResumeParsingResult(BaseModel):
            name: str = Field(default="", description="姓名")
            phone: str = Field(default="", description="手机号")
            email: str = Field(default="", description="邮箱")
            age: Optional[int] = Field(default=None, description="年龄，估测值无则为null")
            gender: Optional[str] = Field(default=None, description="性别，如 '男', '女'")
            desired_position: str = Field(default="", description="期望职位")
            summary: str = Field(default="", description="200字以内的个人总结/个人优势")
            skills: List[str] = Field(default=[], description="技能列表")
            educations: List[Education] = Field(default=[])
            work_experiences: List[WorkExperience] = Field(default=[])

        system_prompt = "你是一个专业的简历解析引擎。运用你的推理能力，将毫无规律的乱码及不规范的文本片段，清洗、纠错并梳理为高度结构化的信息，忽略不相干的特殊符号。"
        user_prompt = f"提取自简历的原始乱码纯文本 (截取最多前 3000 字)：\n{text[:3000]}"

        return await self._call_llm_with_structured_output(system_prompt, user_prompt, ResumeParsingResult)

    async def parse_job_search_intent(self, user_query: str) -> dict:
        """
        【高阶 AI 语义搜索引擎：用户意图拆解解析】
        接收用户杂乱无章、极度口语化的长难句（例如：“我是应届本科不想写代码不想去外包，希望找个离家近薪水过八千的活”），
        推理并转换成对应的 ElasticSearch 的强类型搜索语句骨架，填补薪金上下限与包含排除词汇。
        
        Args:
            user_query (str): C 端用户的口水原话输入。
            
        Returns:
            dict: 提取所得的、极其适合映射进 Query Builder 的约束意图参数集。
        """
        class JobSearchIntent(BaseModel):
            locations: List[str] = Field(default=[], description="地点/城市。比如 '北京', '杭州'。")
            keywords: List[str] = Field(default=[], description="岗位通配词、职能大类。比如 '后端开发', '产品经理'。")
            skills_must_have: List[str] = Field(default=[], description="明确点名的技术栈或工具。比如 'Python', 'Golang', 'Figma'。")
            salary_min: Optional[int] = Field(default=None, description="最低月薪要求(单位:人民币元)。如 '2万' 记为 20000。")
            salary_max: Optional[int] = Field(default=None, description="最高月薪要求(单位:人民币元)。如 '不超过3万' 记为 30000。")
            exclude_keywords: List[str] = Field(default=[], description="用户明确排斥的词汇。如 '不要外包' -> ['外包']。")
            benefits_desired: List[str] = Field(default=[], description="期望的公司福利。如 '双休', '不加班', '五险一金'。")
            education: Optional[str] = Field(default=None, description="学历要求。如 '本科' 或 '大专'。")
            experience: Optional[str] = Field(default=None, description="经验年限要求。如 '1-3年', '应届生', '5-10年'。")
            industry: Optional[str] = Field(default=None, description="行业类型。如 '互联网', '游戏行业'。")

        system_prompt = "你是一个聪明的意图解析器。不论用户的语言多么口语化，你都能精确抽象出过滤条件。对于无法判断的字段必须严格留空。"
        user_prompt = f"用户的口语化找工作原话：【{user_query}】"

        return await self._call_llm_with_structured_output(system_prompt, user_prompt, JobSearchIntent)

    async def _call_llm_with_structured_output(self, system_prompt: str, user_prompt: str, schema: Type[BaseModel]) -> dict:
        """
        【架构重构：基于 LangChain v0.2 的强约束结构化输出 (Structured Outputs)】
        使用 ChatOpenAI 的 .with_structured_output() 方法天然挂载 Pydantic Schema。
        依靠 OpenAI Function Calling 能力彻底避免老旧繁琐的“JSON字符串切割解析”，
        带来原生的字段校验拦截及更强烈的语义对齐。
        
        Args:
            system_prompt (str): 系统约束词汇。
            user_prompt (str): 业务侧文本描述。
            schema (Type[BaseModel]): 期望模型严格遵循输出的 Pydantic 数据模型定义。
            
        Returns:
            dict: 严格遵循传入 Pydantic 模型的数据字典。受到全局断路器保护。
        """
        async def _inner():
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_openai import ChatOpenAI
            from langchain_core.output_parsers import PydanticOutputParser
            
            base_url = settings.AI_BASE_URL.rstrip("/")
            llm_kwargs = {
                "model": settings.AI_MODEL,
                "api_key": settings.AI_API_KEY,
                "temperature": 0.1,
                "timeout": settings.AI_LANGCHAIN_TIMEOUT_SECONDS,
            }
            try:
                llm = ChatOpenAI(**llm_kwargs, base_url=base_url)
            except TypeError:
                llm = ChatOpenAI(**llm_kwargs, openai_api_base=base_url)
                
            parser = PydanticOutputParser(pydantic_object=schema)
            format_instructions = parser.get_format_instructions()
            
            # 兼容不支持原生 Structured Output 的模型，直接使用 Prompt 要求输出 JSON
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt + "\n\n{format_instructions}\n请务必只返回合法的 JSON，不要输出任何 markdown 标记、括号里的解释或其它额外的说明文字。"),
                ("user", "{query}")
            ])
            
            chain = prompt | llm | parser
            result = await chain.ainvoke({
                "query": user_prompt,
                "format_instructions": format_instructions
            })
            return result.model_dump()
            
        start_time = time.time()
        try:
            result = await ai_circuit_breaker.call(_inner)
            duration = time.time() - start_time
            ai_call_duration.labels(method="langchain_json").observe(duration)
            ai_calls_total.labels(method="langchain_json", status="success").inc()
            return result
        except CircuitBreakerOpen as e:
            ai_calls_total.labels(method="langchain_json", status="circuit_open").inc()
            logger.warning(f"Circuit breaker open for structured_output: {e}")
            return {"error": "AI 服务暂时不可用（熔断保护中）"}
        except Exception as e:
            ai_calls_total.labels(method="langchain_json", status="failure").inc()
            logger.error(f"Structured Output AI Error: {e}")
            return {}

ai_service = AIService()
