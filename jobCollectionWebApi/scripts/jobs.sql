/*
 Navicat Premium Dump SQL

 Source Server         : postgre
 Source Server Type    : PostgreSQL
 Source Server Version : 180001 (180001)
 Source Host           : localhost:5432
 Source Catalog        : job
 Source Schema         : public

 Target Server Type    : PostgreSQL
 Target Server Version : 180001 (180001)
 File Encoding         : 65001

 Date: 24/02/2026 13:56:05
*/


-- ----------------------------
-- Table structure for jobs
-- ----------------------------
DROP TABLE IF EXISTS "public"."jobs";
CREATE TABLE "public"."jobs" (
  "id" int8 NOT NULL,
  "title" varchar(255) COLLATE "pg_catalog"."default" NOT NULL,
  "description" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "requirements" text COLLATE "pg_catalog"."default" DEFAULT ''::text,
  "salary_min" float8,
  "salary_max" float8,
  "salary_unit" varchar(20) COLLATE "pg_catalog"."default",
  "salary_desc" varchar(50) COLLATE "pg_catalog"."default",
  "boss_name" varchar(50) COLLATE "pg_catalog"."default",
  "boss_title" varchar(50) COLLATE "pg_catalog"."default",
  "boss_avatar" varchar(255) COLLATE "pg_catalog"."default",
  "experience" varchar(50) COLLATE "pg_catalog"."default",
  "education" varchar(50) COLLATE "pg_catalog"."default",
  "location" varchar(100) COLLATE "pg_catalog"."default",
  "area_district" varchar(100) COLLATE "pg_catalog"."default",
  "business_district" varchar(100) COLLATE "pg_catalog"."default",
  "longitude" float8,
  "latitude" float8,
  "tags" jsonb,
  "welfare" jsonb,
  "work_type" varchar(50) COLLATE "pg_catalog"."default",
  "source_site" varchar(50) COLLATE "pg_catalog"."default",
  "source_url" varchar(255) COLLATE "pg_catalog"."default",
  "publish_date" timestamp(6),
  "encrypt_job_id" varchar(100) COLLATE "pg_catalog"."default",
  "job_labels" jsonb,
  "company_id" int8,
  "industry_code" int4,
  "city_code" int4,
  "industry_id" int8,
  "created_at" timestamp(6),
  "updated_at" timestamp(6),
  "is_active" bool,
  "is_crawl" int2,
  "major_name" varchar(255) COLLATE "pg_catalog"."default",
  "ai_parsed" int2 DEFAULT 0,
  "ai_summary" text COLLATE "pg_catalog"."default",
  "ai_skills" jsonb,
  "ai_benefits" jsonb
)
;
COMMENT ON COLUMN "public"."jobs"."encrypt_job_id" IS 'Boss直聘 encryptJobId';
COMMENT ON COLUMN "public"."jobs"."is_crawl" IS '是否已抓取详情';
COMMENT ON COLUMN "public"."jobs"."major_name" IS '专业名称';
COMMENT ON COLUMN "public"."jobs"."ai_parsed" IS '0:未解析, 1:解析中, 2:已解析';
COMMENT ON COLUMN "public"."jobs"."ai_summary" IS 'AI一句话职责总结';
COMMENT ON COLUMN "public"."jobs"."ai_skills" IS 'AI提取的技能标签数组';
COMMENT ON COLUMN "public"."jobs"."ai_benefits" IS 'AI提取的福利待遇数组';

-- ----------------------------
-- Indexes structure for table jobs
-- ----------------------------
CREATE INDEX "ix_jobs_city_code" ON "public"."jobs" USING btree (
  "city_code" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "ix_jobs_company_id" ON "public"."jobs" USING btree (
  "company_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE UNIQUE INDEX "ix_jobs_encrypt_job_id" ON "public"."jobs" USING btree (
  "encrypt_job_id" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE INDEX "ix_jobs_id" ON "public"."jobs" USING btree (
  "id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "ix_jobs_industry_code" ON "public"."jobs" USING btree (
  "industry_code" "pg_catalog"."int4_ops" ASC NULLS LAST
);
CREATE INDEX "ix_jobs_industry_id" ON "public"."jobs" USING btree (
  "industry_id" "pg_catalog"."int8_ops" ASC NULLS LAST
);
CREATE INDEX "ix_jobs_title" ON "public"."jobs" USING btree (
  "title" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);
CREATE UNIQUE INDEX "source_url" ON "public"."jobs" USING btree (
  "source_url" COLLATE "pg_catalog"."default" "pg_catalog"."text_ops" ASC NULLS LAST
);

-- ----------------------------
-- Uniques structure for table jobs
-- ----------------------------
ALTER TABLE "public"."jobs" ADD CONSTRAINT "jobs_source_url_key" UNIQUE ("source_url");

-- ----------------------------
-- Primary Key structure for table jobs
-- ----------------------------
ALTER TABLE "public"."jobs" ADD CONSTRAINT "jobs_pkey" PRIMARY KEY ("id");
