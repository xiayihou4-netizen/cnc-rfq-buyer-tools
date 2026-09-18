from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


API_ROOT = "https://api.github.com"
TRUSTED_PAYMENT_BOTS = {"algora-pbc"}
MIN_REWARD_USD = 19.0
MAX_REASONABLE_REWARD_USD = 10_000.0
RED_FLAGS = {
    "engagement manipulation": re.compile(r"\b(star|follow)\b.{0,40}\b(repository|account|github)\b", re.I | re.S),
    "crypto or mining": re.compile(r"\b(airdrop|mine|mining|wallet seed|token giveaway)\b", re.I),
    "upfront payment": re.compile(r"\b(pay|purchase|buy)\b.{0,30}\b(first|fee|access|eligibility)\b", re.I | re.S),
    "impossible task": re.compile(r"exact value of (pi|π)|last decimal (of|for) (pi|π)", re.I),
}


@dataclasses.dataclass
class Candidate:
    url: str
    title: str
    repository: str
    reward_usd: float | None
    reward_source: str | None
    score: int
    decision: str
    reasons: list[str]
    comments: int
    repo_stars: int
    repo_archived: bool
    updated_at: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def github_request(path: str, token: str | None = None) -> Any:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-income-bounty-scout/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def parse_money(text: str) -> list[float]:
    patterns = (
        r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        r"\bUSD\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\b",
        r"\b([0-9](?:[0-9,]*[0-9])?(?:\.[0-9]{1,2})?)\s*USD\b",
    )
    values: list[float] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            value = float(match.group(1).replace(",", ""))
            if 0 < value <= MAX_REASONABLE_REWARD_USD:
                values.append(value)
    return values


def find_red_flags(text: str) -> list[str]:
    return [name for name, pattern in RED_FLAGS.items() if pattern.search(text)]


def trusted_reward(comments: Iterable[dict[str, Any]]) -> tuple[float | None, str | None]:
    for comment in comments:
        login = ((comment.get("user") or {}).get("login") or "").lower()
        if login not in TRUSTED_PAYMENT_BOTS:
            continue
        amounts = parse_money(comment.get("body") or "")
        if amounts:
            return max(amounts), login
    return None, None


def days_old(timestamp: str, now: dt.datetime | None = None) -> int:
    now = now or dt.datetime.now(dt.timezone.utc)
    parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return max(0, (now - parsed).days)


def evaluate(
    issue: dict[str, Any],
    repo: dict[str, Any],
    comments: list[dict[str, Any]],
    now: dt.datetime | None = None,
) -> Candidate:
    body = issue.get("body") or ""
    title = issue.get("title") or ""
    combined = f"{title}\n{body}\n" + "\n".join(c.get("body") or "" for c in comments)
    flags = find_red_flags(combined)
    reward, source = trusted_reward(comments)
    score = 0
    reasons: list[str] = []

    if reward is not None:
        score += 35
        reasons.append(f"可信付款机器人确认 ${reward:g}")
        if reward >= MIN_REWARD_USD:
            score += 15
            reasons.append("单笔金额可覆盖月目标")
    else:
        score -= 35
        reasons.append("没有可信付款机器人确认金额")

    stars = int(repo.get("stargazers_count") or 0)
    if stars >= 100:
        score += 12
        reasons.append("仓库有一定社区基础")
    elif stars < 10:
        score -= 12
        reasons.append("仓库社区信号很弱")

    archived = bool(repo.get("archived"))
    if archived:
        score -= 100
        reasons.append("仓库已归档")

    age = days_old(issue.get("updated_at") or issue.get("created_at"), now)
    if age <= 14:
        score += 8
        reasons.append("事项近期活跃")
    elif age > 90:
        score -= 20
        reasons.append("事项超过 90 天未更新")

    comment_count = int(issue.get("comments") or len(comments))
    if comment_count > 50:
        score -= 50
        reasons.append("竞争或噪声极高")
    elif comment_count > 25:
        score -= 30
        reasons.append("竞争或噪声过高")
    elif comment_count <= 5:
        score += 8
        reasons.append("当前竞争较低")

    if re.search(r"acceptance criteria|验收标准|deliverables|done when", body, re.I):
        score += 10
        reasons.append("验收条件较明确")
    else:
        score -= 5
        reasons.append("验收条件不够明确")

    if flags:
        score -= 100
        reasons.extend(f"风险：{flag}" for flag in flags)

    if score >= 55 and reward is not None and not flags:
        decision = "review"
    elif score >= 30 and reward is not None and not flags:
        decision = "watch"
    else:
        decision = "reject"

    repository = (issue.get("repository_url") or "").removeprefix(f"{API_ROOT}/repos/")
    return Candidate(
        url=issue.get("html_url") or "",
        title=title,
        repository=repository,
        reward_usd=reward,
        reward_source=source,
        score=score,
        decision=decision,
        reasons=reasons,
        comments=comment_count,
        repo_stars=stars,
        repo_archived=archived,
        updated_at=issue.get("updated_at") or "",
    )


def discover(limit: int, token: str | None) -> list[Candidate]:
    queries = [
        'is:issue is:open label:bounty "algora"',
        'is:issue is:open "algora-pbc" in:comments',
    ]
    seen: set[str] = set()
    candidates: list[Candidate] = []
    inspection_limit = min(max(limit * 3, 15), 25)
    for query in queries:
        encoded = urllib.parse.quote_plus(f"{query} sort:updated-desc")
        payload = github_request(f"/search/issues?q={encoded}&per_page={min(limit * 3, 30)}", token)
        for issue in payload.get("items", []):
            url = issue.get("html_url") or ""
            if not url or url in seen or issue.get("pull_request"):
                continue
            seen.add(url)
            repository = (issue.get("repository_url") or "").removeprefix(f"{API_ROOT}/repos/")
            if "/" not in repository:
                continue
            repo = github_request(f"/repos/{repository}", token)
            comments = github_request(
                f"/repos/{repository}/issues/{issue['number']}/comments?per_page=100", token
            )
            candidates.append(evaluate(issue, repo, comments))
            if len(candidates) >= inspection_limit:
                break
        if len(candidates) >= inspection_limit:
            break
    return sorted(candidates, key=lambda item: item.score, reverse=True)[:limit]


def write_reports(candidates: list[Candidate], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = dt.datetime.now(dt.timezone.utc).isoformat()
    json_payload = {"generated_at": generated, "candidates": [c.as_dict() for c in candidates]}
    (output_dir / "latest.json").write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = ["# GitHub 悬赏候选", "", f"生成时间：{generated}", ""]
    if not candidates:
        lines.append("本次没有发现可评估候选。")
    for candidate in candidates:
        reward = f"${candidate.reward_usd:g}" if candidate.reward_usd is not None else "未验证"
        lines.extend(
            [
                f"## [{candidate.title}]({candidate.url})",
                "",
                f"- 决策：`{candidate.decision}`",
                f"- 评分：{candidate.score}",
                f"- 验证金额：{reward}",
                f"- 仓库：`{candidate.repository}`（{candidate.repo_stars} Stars）",
                f"- 评论数：{candidate.comments}",
                "- 依据：" + "；".join(candidate.reasons),
                "",
            ]
        )
    (output_dir / "latest.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="筛选可信 GitHub 悬赏")
    parser.add_argument("--limit", type=int, default=8, help="最多评估的候选数")
    parser.add_argument("--output", type=Path, default=Path("reports"), help="报告目录")
    args = parser.parse_args()
    if not 1 <= args.limit <= 30:
        parser.error("--limit 必须在 1 到 30 之间")

    try:
        candidates = discover(args.limit, os.environ.get("GITHUB_TOKEN"))
        write_reports(candidates, args.output)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        print(f"GitHub API 请求失败：{exc}", file=sys.stderr)
        return 2

    review_count = sum(candidate.decision == "review" for candidate in candidates)
    print(f"已评估 {len(candidates)} 个候选，其中 {review_count} 个进入人工复核。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

