import os
import re
import glob
from pathlib import Path

# ==========================================
# 1. 配置路径
# ==========================================
base_dir = r"d:\Code\job\jobCollectionWebApi"
schemas_dir = os.path.join(base_dir, "schemas")

# 获取你要重命名的所有 schemas 模块名（去掉后缀）
schema_modules = []
for file in os.listdir(schemas_dir):
    if file.endswith(".py") and file != "__init__.py" and not file.endswith("_schema.py"):
        schema_modules.append(file[:-3])

print(f"[*] Found {len(schema_modules)} schema files to rename:")
print(schema_modules)

# ==========================================
# 2. 修改文件内容 (修复 Import)
# ==========================================
def fix_imports_in_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content
    
    for mod in schema_modules:
        # absolute imports: from schemas.job_schema import -> from schemas.job_schema import
        content = re.sub(rf"from schemas\.{mod}\b", f"from schemas.{mod}_schema", content)
        # absolute imports: import schemas.job_schema -> import schemas.job_schema
        content = re.sub(rf"import schemas\.{mod}\b", f"import schemas.{mod}_schema", content)
        # schemas.__init__.py or relative imports: from .job_schema import -> from .job_schema import
        if "schemas" in filepath:
            content = re.sub(rf"from \.{mod}\b", f"from .{mod}_schema", content)

    if content != original_content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  [+] Updated imports in {os.path.relpath(filepath, base_dir)}")

# ==========================================
# 3. 遍历整个项目修复引用
# ==========================================
print("\n[*] Updating references across the project...")
for ext in ["**/*.py"]:
    for filepath in glob.glob(os.path.join(base_dir, ext), recursive=True):
        if "venv" in filepath or "site-packages" in filepath or ".git" in filepath or "__pycache__" in filepath:
            continue
        try:
            fix_imports_in_file(filepath)
        except Exception as e:
            pass # simply skip unreadable files

# ==========================================
# 4. 执行重命名操作
# ==========================================
print("\n[*] Renaming schema files...")
for mod in schema_modules:
    old_path = os.path.join(schemas_dir, f"{mod}.py")
    new_path = os.path.join(schemas_dir, f"{mod}_schema.py")
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        print(f"  [-] Renamed {mod}.py -> {mod}_schema.py")

print("\n[SUCCESS] Global schema refactoring completed.")
