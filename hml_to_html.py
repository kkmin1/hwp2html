import re
import base64
import os
import sys
import xml.etree.ElementTree as ET

def hwp_equation_to_latex(script):
    """Robust conversion of HWP equation script to LaTeX."""
    if not script: return ""
    
    # 1. Pre-processing
    script = script.replace('`', ' ')
    
    # 2. Greek letters
    greek = ['alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta', 
             'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'omicron', 'pi', 'rho', 
             'sigma', 'tau', 'upsilon', 'phi', 'chi', 'psi', 'omega']
    for g in greek:
        script = re.sub(r'\b' + g + r'\b', '\\\\' + g, script)
        script = re.sub(r'\b' + g.capitalize() + r'\b', '\\\\' + g.capitalize(), script)

    # 3. Handle 'over' (fractions) recursively for nesting
    def convert_over(s):
        prev_s = ""
        while prev_s != s:
            prev_s = s
            # Match {group} over {group} - innermost first
            s = re.sub(r'\{([^{}]*)\}\s*over\s*\{([^{}]*)\}', r'\\frac{\1}{\2}', s)
            # Match token over token (simple cases like a over b)
            s = re.sub(r'(\b\w+[\^_{}\w]*)\s*over\s*(\b\w+[\^_{}\w]*)', r'\\frac{\1}{\2}', s)
        return s

    script = convert_over(script)

    # 4. Math symbols and operators
    script = script.replace('times', '\\times')
    script = script.replace('root', '\\sqrt')
    script = script.replace('SQRT', '\\sqrt')
    script = script.replace('*', '\\cdot')
    
    # 5. Spacing and scripts
    script = re.sub(r'(\S)\s*\^', r'\1^', script)
    script = re.sub(r'(\S)\s*\_', r'\1_', script)
    
    # 6. Differentials (common pattern)
    script = re.sub(r'\b(d[a-z])\s*/\s*(dt)\b', r'\\frac{\1}{\2}', script)
    
    # 7. Braces cleanup
    if script.startswith('{') and script.endswith('}'):
        inner = script[1:-1]
        if inner.count('{') == inner.count('}'):
            script = inner

    return script.strip()

def convert_hml_to_html(hml_path, output_dir):
    """General purpose HML to HTML converter."""
    tree = ET.parse(hml_path)
    root = tree.getroot()
    
    # Get base filename for image prefix
    hml_basename = os.path.splitext(os.path.basename(hml_path))[0]
    
    # 1. Extract Images from BINDATASTORAGE
    images = {}
    bindata_storage = root.find('.//BINDATASTORAGE')
    if bindata_storage is not None:
        for bindata in bindata_storage.findall('BINDATA'):
            img_id = bindata.get('Id')
            encoding = bindata.get('Encoding')
            if encoding == 'Base64':
                data = base64.b64decode(bindata.text)
                img_name = f"{hml_basename}_{img_id}.png"
                img_path = os.path.join(output_dir, img_name)
                with open(img_path, 'wb') as f:
                    f.write(data)
                images[img_id] = img_name

    # 2. Extract Styles/Character Shapes
    char_shapes = {}
    char_list = root.find('.//CHARSHAPELIST')
    if char_list is not None:
        for cs in char_list.findall('CHARSHAPE'):
            cs_id = cs.get('Id')
            color_val = int(cs.get('TextColor'))
            # Resolve HML color format (BGR to Hex)
            hex_color = f"#{color_val & 0xFFFFFF:06x}" if color_val != 0 else "#000000"
            is_bold = cs.find('BOLD') is not None
            char_shapes[cs_id] = {
                'color': hex_color,
                'bold': is_bold
            }

    # 3. Parse Body Content
    body_html = ""
    section = root.find('.//SECTION')
    if section is not None:
        for p in section.findall('P'):
            p_html = "<p>"
            text_node = p.find('TEXT')
            if text_node is not None:
                for child in text_node:
                    if child.tag == 'CHAR':
                        txt = child.text if child.text else ""
                        cs_id = child.get('CharShape')
                        style = char_shapes.get(cs_id, {})
                        
                        style_str = f"color: {style.get('color', '#000')};"
                        if style.get('bold'): style_str += " font-weight: bold;"
                        
                        # Use span for individual character styles
                        p_html += f'<span style="{style_str}">{txt}</span>'
                    
                    elif child.tag == 'EQUATION':
                        script_elem = child.find('SCRIPT')
                        script = script_elem.text if script_elem is not None else ""
                        latex = hwp_equation_to_latex(script)
                        p_html += f' \\({latex}\\) '
                    
                    elif child.tag == 'PICTURE':
                        img_elem = child.find('.//IMAGE')
                        if img_elem is not None:
                            img_id = img_elem.get('BinItem')
                            img_src = images.get(img_id, "")
                            p_html += f'<div class="img-container"><img src="{img_src}" class="doc-image"></div>'
            
            p_html += "</p>"
            body_html += p_html

    # 4. Final HTML Construction
    title_node = root.find('.//DOCSUMMARY/TITLE')
    title = title_node.text if title_node is not None else os.path.basename(hml_path)
    
    html_template = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <link rel="stylesheet" href="style.css">
    <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
    <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
    <style>
        .doc-image {{
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            margin: 20px 0;
        }}
        .img-container {{
            text-align: center;
        }}
    </style>
</head>
<body>
    <header>
        <h1>{title}</h1>
    </header>
    <main>
        {body_html}
    </main>
</body>
</html>
"""
    return html_template

if __name__ == "__main__":
    if len(sys.argv) > 1:
        hml_file = sys.argv[1]
    else:
        # Default fallback for convenience
        hml_file = r'c:\연구\동태문제\Goodwin 모형.hml'
        
    output_dir = os.path.dirname(hml_file)
    base_name = os.path.splitext(os.path.basename(hml_file))[0]
    output_path = os.path.join(output_dir, f"{base_name}.html")
    
    print(f"Converting {hml_file} to {output_path}...")
    html_content = convert_hml_to_html(hml_file, output_dir)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Conversion complete.")
