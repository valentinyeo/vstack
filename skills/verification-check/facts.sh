#!/usr/bin/env bash
set -u

[ $# -ge 1 ] || { echo "usage: facts.sh <repo-path | session-name>"; exit 2; }
target="$1"

if [ -d "$target" ]; then
  repo="$target"
else
  line=$("$HOME/.local/share/house-rules/fleet/roster-live" 2>/dev/null | tr ';' '\n' | grep -i -F "$target" | head -1)
  cwd=$(printf '%s' "$line" | grep -o '~/[^ )]*' | head -1)
  repo="${cwd/#\~/$HOME}"
  [ -n "$repo" ] && [ -d "$repo" ] || { echo "no repo found for session '$target'"; exit 2; }
fi
repo=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null) || { echo "not a git repo: $target"; exit 2; }
cd "$repo" || exit 2
git fetch -q origin 2>/dev/null
base=""
for b in $(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null) origin/main origin/master; do
  git rev-parse -q --verify "$b^{commit}" >/dev/null && { base=$b; break; }
done
[ -n "$base" ] || base=HEAD
slug=$(git remote get-url origin 2>/dev/null | sed 's#.*github.com[:/]##;s#\.git$##')
files=$(git ls-tree -r --name-only "$base")
show() { git show "$base:$1" 2>/dev/null; }

echo "## Repo"
echo "slug: $slug"
echo "path: $repo"
echo "branch: $base @ $(git rev-parse --short "$base")"
echo "visibility: $(gh repo view "$slug" --json visibility -q .visibility 2>/dev/null || echo unknown)"
printf 'surface hints:'
echo "$files" | grep -q -E '(^|/)build\.zig$' && printf ' zig'
echo "$files" | grep -q -E '\.ps1$' && printf ' windows-powershell'
echo "$files" | grep -q -E '(^|/)AndroidManifest\.xml$' && printf ' android'
echo "$files" | grep -q -E '\.xcodeproj/|(^|/)Package\.swift$' && printf ' ios'
echo "$files" | grep -q -E '(^|/)wrangler\.(toml|jsonc?)$' && printf ' cloudflare-worker'
echo "$files" | grep -q -E '^package\.json$' && printf ' node:%s' "$(show package.json | grep -o -E '"(next|react|vite|astro|svelte|vue|expo|electron)"' | tr -d '"' | sort -u | tr '\n' ',')"
echo "$files" | grep -q -E '^Cargo\.toml$' && printf ' rust'
echo

echo
echo "## Verify skills"
skills=$(echo "$files" | grep -E '^\.(claude|cursor|agents)/skills/verify-[^/]+/SKILL\.md$')
[ -z "$skills" ] && echo "none"
for s in $skills; do
  d=${s%/SKILL.md}
  echo "- $s ($(show "$s" | wc -l) lines)"
  echo "  headings: $(show "$s" | grep -E '^#{1,3} ' | sed 's/^#* //' | tr '\n' '|' | cut -c1-300)"
  echo "  feature files: $(echo "$files" | grep -c -E "^$d/features/.+\.md$")"
  echo "  helper scripts: $(echo "$files" | grep -E "^$d/[^/]+\.(sh|ps1|mjs|js|py|ts)$" | wc -l)"
done

echo
echo "## Workflows (name: triggers | concurrency)"
for f in $(echo "$files" | grep -E '^\.github/workflows/.+\.ya?ml$'); do
  t=$(show "$f" | awk '/^on:/{f=1;next} f&&/^[a-z]/{exit} f' | grep -o -E '^\s{2}[a-z_]+' | tr -d ' ' | tr '\n' ',')
  c=$(show "$f" | grep -q -E '^concurrency:' && echo yes || echo no)
  echo "- ${f#.github/workflows/}: ${t%,} | $c"
done

echo
echo "## Required checks on $base"
gh api "repos/$slug/branches/${base#origin/}/protection/required_status_checks" -q '.contexts[]' 2>/dev/null || echo "none or no access"

echo
echo "## Agent rule files"
for f in CLAUDE.md AGENTS.md; do
  show "$f" >/dev/null && echo "- $f: $(show "$f" | wc -l) lines, rule-table rows: $(show "$f" | grep -c -E '^\|.*\|.*\|$')"
done

echo
echo "## Recent PR verdicts (last 10 merged)"
gh pr list --repo "$slug" --state merged --limit 10 --json number,title,comments -q '.[]|"#\(.number) \(.title[0:60]) | \([.comments[].body|select(test("pstack-verifier:"))]|last|.[0:60]? // "no verifier comment")"' 2>/dev/null | tr '\n' '\n'
