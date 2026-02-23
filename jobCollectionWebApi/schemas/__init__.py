from .job import JobBase, JobCreate, JobUpdate, JobInDB, JobWithRelations, JobList
from .company import CompanyBase, CompanyCreate, CompanyUpdate, CompanyInDB, CompanyWithJobs, CompanyList
from .skill import SkillBase, SkillCreate, SkillUpdate, SkillInDB, SkillWithJobs, SkillFrequency, SkillFrequencyList, SkillList
from .analysis import AnalysisResultBase, AnalysisResultCreate, AnalysisResultUpdate, AnalysisResultInDB, AnalysisResultList, UserQueryCreate, UserQueryInDB
from .user import UserBase, UserCreate, UserUpdate, UserAdminUpdate, UserInDB, UserPublic, UserDetail, UserStats, UserList, UserRole, UserStatus
from .token import Token, TokenPayload, TokenData, WechatLoginRequest, PhoneLoginRequest, SendSMSRequest, RefreshTokenRequest, LoginResponse

# 解决循环导入
from .job import JobWithRelations
from .company import CompanyWithJobs
from .skill import SkillWithJobs

JobWithRelations.model_rebuild()
CompanyWithJobs.model_rebuild()
SkillWithJobs.model_rebuild()
