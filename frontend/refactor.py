import os
import glob
import re

src_dir = os.path.join(os.path.dirname(__file__), 'src')
core_api_file = os.path.join(src_dir, 'core', 'api.js')
utils_dir = os.path.join(src_dir, 'utils')
request_file = os.path.join(utils_dir, 'request.js')

if not os.path.exists(utils_dir):
    os.makedirs(utils_dir, exist_ok=True)

if os.path.exists(core_api_file):
    os.rename(core_api_file, request_file)
    print("Moved core/api.js to utils/request.js")

for ext in ['**/*.vue', '**/*.js']:
    for file_path in glob.glob(os.path.join(src_dir, ext), recursive=True):
        if not os.path.isfile(file_path):
            continue
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        new_content = re.sub(r'[\'"](.*?)core/api[\'"]', r"'@/utils/request'", content)
        
        if new_content != content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Updated: {file_path}")

print("Done")
