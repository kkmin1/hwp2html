import re
import os

file_path = r'c:\연구\동태문제\Goodwin_모형.html'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace <p> \(... \) </p> with <p style="padding-left: 3ch;"> \(... \) </p>
# We look for <p> followed by any amount of whitespace, then \(
# But we must be careful not to match paragraphs that have text before the math.
# In this file, block math seems to always start with a space after <p>.

new_content = re.sub(r'<p>\s+\\\(', r'<p style="padding-left: 3ch;"> \(', content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Successfully updated Goodwin_모형.html with indentation.")
