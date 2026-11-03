# Renders docs/assets/demo.gif with https://github.com/charmbracelet/vhs
# vhs docs/demo.tape   (run from the repo root, after `uv sync`)
Output docs/assets/demo.gif
Set Shell "bash"
Set FontFamily "JetBrains Mono"
Set FontSize 15
Set Width 1180
Set Height 760
Set Padding 24
Set Theme { "name": "doesitfire", "black": "#0d0d10", "red": "#f66d67", "green": "#5fd37f", "yellow": "#f7b83d", "blue": "#88a9ff", "magenta": "#df8cd8", "cyan": "#88a9ff", "white": "#f4f5f8", "brightBlack": "#a3a4ae", "brightRed": "#f66d67", "brightGreen": "#5fd37f", "brightYellow": "#f7b83d", "brightBlue": "#88a9ff", "brightMagenta": "#df8cd8", "brightCyan": "#88a9ff", "brightWhite": "#ffffff", "background": "#000000", "foreground": "#f4f5f8", "selection": "#28282e", "cursor": "#df8cd8" }
Set TypingSpeed 45ms
Hide
Type "export PS1='$ ' COLUMNS=100 && uv sync -q && clear"
Enter
Sleep 2s
Show
Type "uv run doesitfire demo --no-open --out /tmp/doesitfire-demo"
Sleep 400ms
Enter
Sleep 7s
