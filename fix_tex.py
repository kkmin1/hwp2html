import re
import os

def fix_latex(content):
    # Remove problematic packages
    content = re.sub(r'\\usepackage\{ikps\}', r'', content)
    content = re.sub(r'\\usepackage\{oblivoir\}', r'', content)
    
    # Escape underscores in URLs
    def url_fix(match):
        return match.group(0).replace('_', r'\_')
    content = re.sub(r'http[s]?://[^\s{}]+', url_fix, content)
    
    # Fix common custom commands
    content = content.replace('\\mrm', '\\mathrm')
    
    # Add Title/Author/Date
    if '\\title' not in content:
        content = "\\title{미분방정식과 응용}\n\\author{연구원}\n" + content

    # Goodwin Placeholder
    target_goodwin = "divide the positive orthant into four regions."
    if target_goodwin in content:
        content = content.replace(target_goodwin, target_goodwin + "\n\n@@@TIKZGOODWIN@@@\n\n")

    # Solow Placeholder
    target_solow = "정상상태(steady-state)"
    if target_solow in content:
        content = content.replace(target_solow, "\n\n@@@TIKZSOLOW@@@\n\n" + target_solow)

    return content

tex_path = r'c:\연구\동태문제\hmltotex_미분방정식과 응용\미분방정식과 응용.tex'
fixed_path = r'c:\연구\동태문제\미분방정식_fixed.tex'

with open(tex_path, 'r', encoding='utf-8') as f:
    text = f.read()

fixed_text = fix_latex(text)

with open(fixed_path, 'w', encoding='utf-8') as f:
    f.write(fixed_text)
