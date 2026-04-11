import re

html_path = r'c:\연구\동태문제\미분방정식과 응용.html'

with open(html_path, 'r', encoding='utf-8') as f:
    html = f.read()

# Define TikZ blocks
tikz_goodwin = r"""
<div class="tikz-container">
<script type="text/tikz">
\begin{tikzpicture}[scale=1.2, >=stealth]
    \draw[->, thick] (0,0) -- (5,0) node[right] {$v$};
    \draw[->, thick] (0,0) -- (0,5) node[above] {$u$};
    \draw[dashed] (2.5,0) -- (2.5,5) node[above] {$v^*$};
    \draw[dashed] (0,2.5) -- (5,2.5) node[right] {$u^*$};
    \fill (2.5,2.5) circle (2pt);
    \draw[red, thick, ->] (2.5,2.5) + (1.2,0) arc (0:360:1.2 and 0.9);
    \draw[red, thick, ->] (2.5,2.5) + (2.0,0) arc (0:360:2.0 and 1.5);
    \draw[->, blue, thick] (1, 1) -- (1, 2);
    \draw[->, blue, thick] (4, 1) -- (3, 1);
    \draw[->, blue, thick] (4, 4) -- (4, 3);
    \draw[->, blue, thick] (1, 4) -- (2, 4);
\end{tikzpicture}
</script>
<p style="font-style: italic; font-size: 0.9em;">Goodwin Model Phase Diagram (TikZ)</p>
</div>
"""

tikz_solow = r"""
<div class="tikz-container">
<script type="text/tikz">
\begin{tikzpicture}[scale=1.2, >=stealth]
    \draw[->] (0,0) -- (5,0) node[right] {$k$};
    \draw[->] (0,0) -- (0,4) node[above] {$y$};
    \draw[domain=0:4.5, smooth, variable=\x, blue, thick] plot ({\x}, {1.8*sqrt(\x)}) node[right] {$\phi(k)$};
    \draw[domain=0:4.5, smooth, variable=\x, red, thick] plot ({\x}, {0.6*sqrt(\x)}) node[right] {$s\phi(k)$};
    \draw[domain=0:4.5, smooth, variable=\x, black] plot ({\x}, {0.5*\x}) node[right] {$(n+\delta)k$};
    \fill (3.24, 1.62) circle (2pt) node[below right] {$k^*$};
    \draw[dashed] (3.24,0) -- (3.24, 3.24);
\end{tikzpicture}
</script>
<p style="font-style: italic; font-size: 0.9em;">Solow Growth Model (TikZ)</p>
</div>
"""

# Replace placeholders
html = html.replace("<p>@@@TIKZGOODWIN@@@</p>", tikz_goodwin)
html = html.replace("@@@TIKZGOODWIN@@@", tikz_goodwin)
html = html.replace("<p>@@@TIKZSOLOW@@@</p>", tikz_solow)
html = html.replace("@@@TIKZSOLOW@@@", tikz_solow)
# If not, I'll search for specific text to replace in fix_tex.py later

# Add TikZ-Jax scripts to <head> if not present
if "tikzjax.js" not in html:
    header_tags = """
<link rel="stylesheet" type="text/css" href="https://tikzjax.com/v1/fonts.css">
<script src="https://tikzjax.com/v1/tikzjax.js"></script>
<style>
    .tikz-container {
        padding: 20px;
        background: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        margin: 30px auto;
        max-width: fit-content;
        text-align: center;
    }
</style>
"""
    html = html.replace("</head>", header_tags + "</head>")

with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
