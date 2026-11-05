import os, shutil, re

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))

# Define new directories relative to PROJECT_ROOT
new_dirs = [
    'frontend/components',
    'frontend/pages',
    'frontend/i18n',
    'frontend/static',
    'backend/services',
    'backend',
    'config',
    'scripts',
    'docs',
    'data',
    'tests'
]

# Ensure directories exist
for d in new_dirs:
    os.makedirs(os.path.join(PROJECT_ROOT, d), exist_ok=True)

# Mapping from old location to new location (relative paths)
move_map = {
    'components': 'frontend/components',
    'pages': 'frontend/pages',
    'i18n': 'frontend/i18n',
    'static': 'frontend/static',
    'services': 'backend/services',
    'api.py': 'backend/api.py',
    'generate_icons.py': 'scripts/generate_icons.py',
    '.env.example': 'config/.env.example',
    'requirements.txt': 'config/requirements.txt',
    'README.md': 'docs/README.md'
}

for src, dst in move_map.items():
    src_path = os.path.join(PROJECT_ROOT, src)
    dst_path = os.path.join(PROJECT_ROOT, dst)
    if os.path.isdir(src_path):
        if os.path.abspath(src_path) != os.path.abspath(dst_path):
            if os.path.exists(dst_path):
                # merge contents
                for root, dirs, files in os.walk(src_path):
                    rel = os.path.relpath(root, src_path)
                    target_root = os.path.join(dst_path, rel)
                    os.makedirs(target_root, exist_ok=True)
                    for f in files:
                        shutil.move(os.path.join(root, f), os.path.join(target_root, f))
                shutil.rmtree(src_path)
            else:
                shutil.move(src_path, dst_path)
    elif os.path.isfile(src_path):
        shutil.move(src_path, dst_path)

# Update import statements throughout the project
for root, dirs, files in os.walk(PROJECT_ROOT):
    for f in files:
        if f.endswith('.py'):
            file_path = os.path.join(root, f)
            with open(file_path, 'r', encoding='utf-8') as fh:
                content = fh.read()
            new_content = content
            # components -> frontend.components
            new_content = re.sub(r'from\s+components\.', 'from frontend.components.', new_content)
            new_content = re.sub(r'import\s+components\.', 'import frontend.components.', new_content)
            # pages -> frontend.pages
            new_content = re.sub(r'from\s+pages\.', 'from frontend.pages.', new_content)
            new_content = re.sub(r'import\s+pages\.', 'import frontend.pages.', new_content)
            # services -> backend.services
            new_content = re.sub(r'from\s+services\.', 'from backend.services.', new_content)
            new_content = re.sub(r'import\s+services\.', 'import backend.services.', new_content)
            # Special handling for app.py static path and API import
            if os.path.basename(file_path) == 'app.py':
                new_content = re.sub(r"from\s+api\s+import\s+api_router", "from backend.api import api_router", new_content)
                new_content = re.sub(r"os\.path\.join\(os\.path\.dirname\(__file__\), 'static'\)", "os.path.join(os.path.dirname(__file__), 'frontend', 'static')", new_content)
            if new_content != content:
                with open(file_path, 'w', encoding='utf-8') as fh:
                    fh.write(new_content)

print('Reorganization script executed successfully')
