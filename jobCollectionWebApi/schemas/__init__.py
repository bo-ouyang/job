from .job_schema import JobBase, JobCreate, JobUpdate, JobInDB, JobWithRelations, JobList
from .company_schema import CompanyBase, CompanyCreate, CompanyUpdate, CompanyInDB, CompanyWithJobs, CompanyList
from .skill_schema import SkillBase, SkillCreate, SkillUpdate, SkillInDB, SkillWithJobs, SkillFrequency, SkillFrequencyList, SkillList
from .analysis_schema import AnalysisResultBase, AnalysisResultCreate, AnalysisResultUpdate, AnalysisResultInDB, AnalysisResultList, UserQueryCreate, UserQueryInDB
from .user_schema import UserBase, UserCreate, UserUpdate, UserAdminUpdate, UserInDB, UserPublic, UserDetail, UserStats, UserList, UserRole, UserStatus
from .token_schema import Token, TokenPayload, TokenData, WechatLoginRequest, PhoneLoginRequest, SendSMSRequest, RefreshTokenRequest, LoginResponse

# 解决循环导入
from .job_schema import JobWithRelations
from .company_schema import CompanyWithJobs
from .skill_schema import SkillWithJobs

JobWithRelations.model_rebuild()
CompanyWithJobs.model_rebuild()
SkillWithJobs.model_rebuild()
