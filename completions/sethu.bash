# Bash completion for the `sethu` CLI.
# Install:  echo 'source /path/to/claude-sethu/completions/sethu.bash' >> ~/.bashrc
_sethu() {
  local cur prev flags subs
  cur="${COMP_WORDS[COMP_CWORD]}"
  prev="${COMP_WORDS[COMP_CWORD-1]}"
  flags="--mode --allow --unallow --launch --unlaunch --readonly --trust --rc --color --prefix --restart --runner --help"
  subs="mode allow unallow launch unlaunch readonly trust rc color prefix restart runner help"
  case "$prev" in
    --mode|mode)       COMPREPLY=( $(compgen -W "stateless cwd shell" -- "$cur") ); return ;;
    --readonly|readonly|--trust|trust|--rc|rc|--color|color) COMPREPLY=( $(compgen -W "on off" -- "$cur") ); return ;;
  esac
  if [[ "$cur" == -* ]]; then
    COMPREPLY=( $(compgen -W "$flags" -- "$cur") )
  else
    COMPREPLY=( $(compgen -W "$subs" -- "$cur") )
  fi
}
complete -F _sethu sethu
