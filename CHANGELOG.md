# Changelog

All notable changes are recorded by Release Please from conventional commits.

## [1.1.0](https://github.com/bo-ouyang/job/compare/job-v1.0.0...job-v1.1.0) (2026-08-12)


### Features

* add complete GitHub CI/CD pipeline ([5309f0a](https://github.com/bo-ouyang/job/commit/5309f0ab181f5b6e4d9834986da8a43eac84c3d3))
* add realtime agent responses and task notifications ([3728512](https://github.com/bo-ouyang/job/commit/3728512b0e4f1f2c1ede9317d63aca1d067bfa3a))
* AI弹性架构全链路改造 + 前端异步适配 + Git清理 ([8aedbaa](https://github.com/bo-ouyang/job/commit/8aedbaa5a5441f24e2b6e17bd70ed6b850fad325))
* 增加爬虫远程控制与监控架构 ([57380c1](https://github.com/bo-ouyang/job/commit/57380c1d579e8de1431f922325ca403d11bf0e6d))
* 导入Boss行业与职位分类数据 ([99934fd](https://github.com/bo-ouyang/job/commit/99934fdc83f61e3c004c8506c028af07862c917d))
* 统一封装前端 API 请求模块并配置环境变量 完善爬虫的ip代理池 ([e4b9d2c](https://github.com/bo-ouyang/job/commit/e4b9d2c79876f1fb2894e2025f706bd6fe3e2f89))


### Bug Fixes

* allow release manifest version updates ([b993c42](https://github.com/bo-ouyang/job/commit/b993c42662d47523c858710ba9bdfd94bb89dff6))
* allow verified releases to skip redundant push ([ccd1203](https://github.com/bo-ouyang/job/commit/ccd12035cc09a68e8d2e5b36b3bde8c34ff9d62f))
* approve Release Please PR checks ([8a521fb](https://github.com/bo-ouyang/job/commit/8a521fb320a6bc874bd6ff8d6d80f646b8676e56))
* bootstrap releases from Git bundles ([518dc10](https://github.com/bo-ouyang/job/commit/518dc1037009afd3a4b2aeff95940f8dfd5a2e41))
* create bootstrap bundles from the HEAD ref ([35e1224](https://github.com/bo-ouyang/job/commit/35e1224a0e0c9d937d60813e7ba6c9625288b902))
* harden cross-platform Docker release checks ([b1eaf83](https://github.com/bo-ouyang/job/commit/b1eaf834f10c147a9b9e7f49f7bd296af5c2d954))
* harden Docker release preflight ([ba04a82](https://github.com/bo-ouyang/job/commit/ba04a82263486c1808df57f0db753f6eb0a92652))
* include backend task contract dependency ([8e4816d](https://github.com/bo-ouyang/job/commit/8e4816d0a37fcbb47e8fed1dbb3be3d2a437a77d))
* retry remote Git transfers over HTTP 1.1 ([d81cbc6](https://github.com/bo-ouyang/job/commit/d81cbc6c175b910c21430afd35a217ac8eec48b3))
* surface AI provider quota failures ([2faf9c5](https://github.com/bo-ouyang/job/commit/2faf9c55518dea219d231c096ed5c119d9a354e8))
* use bounded shallow clones for releases ([9e6e493](https://github.com/bo-ouyang/job/commit/9e6e4939640918b87100e91aceef41d92add6f5a))
* use reachable dependency mirrors in Docker builds ([4a520c0](https://github.com/bo-ouyang/job/commit/4a520c02b80209f1e04c0913a975a72be41b924d))
* 修复上线安全与生产配置 ([6f1b611](https://github.com/bo-ouyang/job/commit/6f1b611a6cec77a28ef3df11d2be3901d7e5fcd8))
* 修复后台部署与生产迁移兼容性 ([8dcf554](https://github.com/bo-ouyang/job/commit/8dcf55430f17b701ae4161e35a4e3487cea8fdc2))
* 修复首页筛选并补全职业分析数据 ([eec9028](https://github.com/bo-ouyang/job/commit/eec902890c8b3ff9d89d600fa345a24a93385373))
* 让职业筛选结果始终包含所选项 ([f9ef7e8](https://github.com/bo-ouyang/job/commit/f9ef7e8463e82d598ce8f063dc8127df86a33392))

## 1.0.0 (2026-08-11)

- Established the production Docker Compose baseline for the frontend and Web API.
- Added database backup, migration, health-check, and application rollback guards.
