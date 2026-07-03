# scripts/project_audit.py
import os
import re
import ast
import sys

PROJECT_ROOT = r"C:\Users\ADMIN\VS CODE\Project\SpaManager"
EXCLUDE_DIRS = ['venv', '.git', '__pycache__', '.vscode', 'instance', 'build', 'exports']


def get_all_files(root_dir, extensions=None):
    files_list = []
    for root, dirs, files in os.walk(root_dir):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            if extensions:
                if any(file.endswith(ext) for ext in extensions):
                    files_list.append(os.path.join(root, file))
            else:
                files_list.append(os.path.join(root, file))
    return files_list


def scan_python_imports(py_files):
    unused_imports = []
    duplicate_imports = []
    wildcard_imports = []

    for filepath in py_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                code = f.read()
        except Exception as e:
            continue

        try:
            tree = ast.parse(code, filename=filepath)
        except SyntaxError:
            continue

        imported_names = {}  # name -> (node, line_no, alias_name)
        wildcards = []
        
        # Walk AST to find imports and usages
        class ImportVisitor(ast.NodeVisitor):
            def visit_Import(self, node):
                for alias in node.names:
                    name = alias.asname or alias.name
                    imported_names[name] = (node, node.lineno, alias.name)
                self.generic_visit(node)

            def visit_ImportFrom(self, node):
                if node.names[0].name == '*':
                    wildcards.append((node, node.lineno, node.module))
                else:
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names[name] = (node, node.lineno, alias.name)
                self.generic_visit(node)

        visitor = ImportVisitor()
        visitor.visit(tree)

        # Track name usages in the AST (excluding the import statement itself)
        used_names = set()

        class UsageVisitor(ast.NodeVisitor):
            def visit_Name(self, node):
                if isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)
                self.generic_visit(node)

            def visit_Attribute(self, node):
                # E.g., module.attribute
                self.generic_visit(node)

        UsageVisitor().visit(tree)

        # 1. Unused imports check
        for name, (node, lineno, orig_name) in imported_names.items():
            if name not in used_names:
                unused_imports.append({
                    'file': os.path.relpath(filepath, PROJECT_ROOT),
                    'line': lineno,
                    'name': name
                })

        # 2. Duplicate imports check (raw text parse is easier for exact dup lines)
        lines = code.splitlines()
        seen_imports = {}
        for idx, line in enumerate(lines, 1):
            cleaned = line.strip()
            if (cleaned.startswith('import ') or cleaned.startswith('from ')) and ';' not in cleaned:
                if cleaned in seen_imports:
                    duplicate_imports.append({
                        'file': os.path.relpath(filepath, PROJECT_ROOT),
                        'line': idx,
                        'content': cleaned,
                        'first_line': seen_imports[cleaned]
                    })
                else:
                    seen_imports[cleaned] = idx

        # 3. Wildcard imports
        for node, lineno, module in wildcards:
            wildcard_imports.append({
                'file': os.path.relpath(filepath, PROJECT_ROOT),
                'line': lineno,
                'module': module
            })

    return unused_imports, duplicate_imports, wildcard_imports


def scan_todos(files):
    todo_list = []
    # Match patterns like TODO, FIXME, HACK, XXX
    pattern = re.compile(r'\b(TODO|FIXME|HACK|XXX)\b:?\s*(.*)', re.IGNORECASE)

    for filepath in files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for idx, line in enumerate(f, 1):
                    match = pattern.search(line)
                    if match:
                        todo_type = match.group(1).upper()
                        text = match.group(2).strip()
                        todo_list.append({
                            'file': os.path.relpath(filepath, PROJECT_ROOT),
                            'line': idx,
                            'type': todo_type,
                            'text': text
                        })
        except Exception:
            continue
    return todo_list


def scan_empty_folders(root_dir):
    empty_dirs = []
    for root, dirs, files in os.walk(root_dir):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        # Check if empty (excluding pycache)
        if not dirs and not files:
            empty_dirs.append(os.path.relpath(root, PROJECT_ROOT))
        elif len(files) == 0 and len(dirs) == 1 and dirs[0] == '__pycache__':
            empty_dirs.append(os.path.relpath(root, PROJECT_ROOT))
    return empty_dirs


def scan_duplicate_css_selectors(css_files):
    duplicates = []
    # Basic CSS parser to detect duplicate selectors in the same file
    for filepath in css_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        # Strip comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Find all selectors (simple regex matching anything before `{`)
        seen_selectors = {}
        # Regex matches block selectors e.g., .class, #id { ... }
        matches = re.finditer(r'([^{]+)\{', content)
        for m in matches:
            selector_group = m.group(1).strip()
            # Split grouped selectors e.g. h1, h2 -> ['h1', 'h2']
            selectors = [s.strip() for s in selector_group.split(',')]
            for s in selectors:
                if not s or s.startswith('@'): # Skip media queries or keyframe lines
                    continue
                if s in seen_selectors:
                    duplicates.append({
                        'file': os.path.relpath(filepath, PROJECT_ROOT),
                        'selector': s,
                        'occurrences': seen_selectors[s] + 1
                    })
                    seen_selectors[s] += 1
                else:
                    seen_selectors[s] = 1
    return duplicates


def scan_duplicate_js_functions(js_files):
    duplicates = []
    for filepath in js_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception:
            continue

        # Find named function declarations: function name(...)
        matches = re.finditer(r'\bfunction\s+([a-zA-Z0-9_$]+)\s*\(', content)
        seen_functions = {}
        for idx, m in enumerate(matches):
            func_name = m.group(1)
            # Find line number
            line_no = content[:m.start()].count('\n') + 1
            if func_name in seen_functions:
                duplicates.append({
                    'file': os.path.relpath(filepath, PROJECT_ROOT),
                    'line': line_no,
                    'function': func_name,
                    'first_line': seen_functions[func_name]
                })
            else:
                seen_functions[func_name] = line_no
    return duplicates


def scan_dead_templates(html_files, py_files, js_files):
    dead_templates = []
    
    # 1. Gather all rendered templates in python files (e.g., render_template('service/index.html'))
    # 2. Gather all template inclusions in HTML templates (e.g., include 'layout/flash.html')
    references = set()
    
    # Scan python files for render_template
    pattern_py = re.compile(r'render_template\(\s*[\'"]([^\'"]+)[\'"]')
    for py_file in py_files:
        try:
            content = open(py_file, 'r', encoding='utf-8').read()
            for match in pattern_py.finditer(content):
                references.add(match.group(1).replace('\\', '/'))
        except Exception:
            pass

    # Scan HTML files for extends/include
    pattern_html = re.compile(r'{%\s*(?:include|extends)\s+[\'"]([^\'"]+)[\'"]\s*%}')
    for html_file in html_files:
        try:
            content = open(html_file, 'r', encoding='utf-8').read()
            for match in pattern_html.finditer(content):
                references.add(match.group(1).replace('\\', '/'))
        except Exception:
            pass

    # Compare HTML files with references
    for html_file in html_files:
        rel_path = os.path.relpath(html_file, os.path.join(PROJECT_ROOT, 'templates')).replace('\\', '/')
        if rel_path not in references:
            # Check exceptions: layout.html, index.html might be base or main files
            if rel_path in ['layout.html', 'base.html', 'index.html']:
                continue
            dead_templates.append(rel_path)
            
    return dead_templates


def main():
    py_files = get_all_files(PROJECT_ROOT, ['.py'])
    js_files = get_all_files(PROJECT_ROOT, ['.js'])
    css_files = get_all_files(PROJECT_ROOT, ['.css'])
    html_files = get_all_files(PROJECT_ROOT, ['.html'])
    all_files = py_files + js_files + css_files + html_files

    print("Running audit...")
    unused_imports, duplicate_imports, wildcard_imports = scan_python_imports(py_files)
    todos = scan_todos(all_files)
    empty_folders = scan_empty_folders(PROJECT_ROOT)
    duplicate_css = scan_duplicate_css_selectors(css_files)
    duplicate_js = scan_duplicate_js_functions(js_files)
    dead_templates = scan_dead_templates(html_files, py_files, js_files)

    # Generate Markdown Report
    report_path = os.path.join(PROJECT_ROOT, 'docs', 'CLEANUP_REPORT.md')
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("# Báo Cáo Dọn Dẹp Mã Nguồn (Code Cleanup Report)\n\n")
        f.write(f"Ngày lập báo cáo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # 1. Unused Imports
        f.write("## 1. Unused Python Imports\n")
        if unused_imports:
            f.write("| Tệp tin | Dòng | Thư viện không dùng |\n")
            f.write("| --- | --- | --- |\n")
            for item in unused_imports:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | {item['line']} | `{item['name']}` |\n")
        else:
            f.write("Không phát hiện unused imports.\n")
        f.write("\n")

        # 2. Duplicate Imports
        f.write("## 2. Duplicate Python Imports\n")
        if duplicate_imports:
            f.write("| Tệp tin | Dòng | Dòng import bị trùng | Dòng xuất hiện đầu tiên |\n")
            f.write("| --- | --- | --- | --- |\n")
            for item in duplicate_imports:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | {item['line']} | `{item['content']}` | {item['first_line']} |\n")
        else:
            f.write("Không phát hiện duplicate imports.\n")
        f.write("\n")

        # 3. Wildcard Imports
        f.write("## 3. Wildcard Python Imports\n")
        if wildcard_imports:
            f.write("| Tệp tin | Dòng | Module nhập khẩu wildcard |\n")
            f.write("| --- | --- | --- |\n")
            for item in wildcard_imports:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | {item['line']} | `from {item['module']} import *` |\n")
        else:
            f.write("Không phát hiện wildcard imports.\n")
        f.write("\n")

        # 4. Duplicate CSS Selectors
        f.write("## 4. Duplicate CSS Selectors\n")
        if duplicate_css:
            f.write("| Tệp tin | Selector trùng | Số lần xuất hiện |\n")
            f.write("| --- | --- | --- |\n")
            for item in duplicate_css:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | `{item['selector']}` | {item['occurrences']} |\n")
        else:
            f.write("Không phát hiện duplicate CSS selectors.\n")
        f.write("\n")

        # 5. Duplicate JS Functions
        f.write("## 5. Duplicate JavaScript Functions\n")
        if duplicate_js:
            f.write("| Tệp tin | Dòng trùng | Tên Function | Dòng xuất hiện đầu tiên |\n")
            f.write("| --- | --- | --- | --- |\n")
            for item in duplicate_js:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | {item['line']} | `{item['function']}` | {item['first_line']} |\n")
        else:
            f.write("Không phát hiện duplicate JavaScript functions.\n")
        f.write("\n")

        # 6. Dead Templates
        f.write("## 6. Dead / Unused HTML Templates\n")
        if dead_templates:
            f.write("| Tên Template | Đường dẫn tương đối |\n")
            f.write("| --- | --- |\n")
            for item in dead_templates:
                f.write(f"| `{os.path.basename(item)}` | `templates/{item}` |\n")
        else:
            f.write("Không phát hiện dead templates.\n")
        f.write("\n")

        # 7. Empty Folders
        f.write("## 7. Empty Directories\n")
        if empty_folders:
            f.write("| Thư mục rỗng |\n")
            f.write("| --- |\n")
            for item in empty_folders:
                f.write(f"| `{item}` |\n")
        else:
            f.write("Không phát hiện thư mục rỗng.\n")
        f.write("\n")

        # 8. TODO / FIXME / HACK List
        f.write("## 8. TODO / FIXME / HACK / XXX Items\n")
        if todos:
            f.write("| Tệp tin | Dòng | Loại | Mô tả |\n")
            f.write("| --- | --- | --- | --- |\n")
            for item in todos:
                f_url = item['file'].replace('\\', '/')
                f.write(f"| [{item['file']}](file:///{PROJECT_ROOT}/{f_url}) | {item['line']} | **{item['type']}** | {item['text']} |\n")
        else:
            f.write("Không phát hiện TODO items.\n")
        f.write("\n")

    print(f"Audit completed. Report saved to: {report_path}")


if __name__ == "__main__":
    from datetime import datetime
    main()
