import datetime as dt
import unittest

from bounty_scout import evaluate, find_red_flags, parse_money, trusted_reward


NOW = dt.datetime(2026, 9, 18, tzinfo=dt.timezone.utc)


def base_issue(**overrides):
    issue = {
        "html_url": "https://github.com/example/project/issues/7",
        "repository_url": "https://api.github.com/repos/example/project",
        "title": "Add export support",
        "body": "Acceptance Criteria\n- export JSON\n- add tests",
        "comments": 3,
        "created_at": "2026-09-10T00:00:00Z",
        "updated_at": "2026-09-17T00:00:00Z",
    }
    issue.update(overrides)
    return issue


def base_repo(**overrides):
    repo = {"stargazers_count": 350, "archived": False}
    repo.update(overrides)
    return repo


class MoneyParsingTests(unittest.TestCase):
    def test_parses_supported_usd_formats(self):
        self.assertEqual(parse_money("$30, USD 25 and 40 USD"), [30.0, 25.0, 40.0])

    def test_ignores_implausible_amount(self):
        self.assertEqual(parse_money("$239398281948585883"), [])


class TrustTests(unittest.TestCase):
    def test_only_trusted_bot_confirms_reward(self):
        comments = [
            {"user": {"login": "random-user"}, "body": "$500 bounty"},
            {"user": {"login": "algora-pbc"}, "body": "Offering a $30 bounty"},
        ]
        self.assertEqual(trusted_reward(comments), (30.0, "algora-pbc"))

    def test_rejects_engagement_manipulation(self):
        self.assertIn("engagement manipulation", find_red_flags("Star the repository to qualify"))


class ScoringTests(unittest.TestCase):
    def test_good_candidate_reaches_review(self):
        comments = [{"user": {"login": "algora-pbc"}, "body": "Offering a $30 bounty"}]
        result = evaluate(base_issue(), base_repo(), comments, NOW)
        self.assertEqual(result.decision, "review")
        self.assertEqual(result.reward_usd, 30.0)

    def test_crowded_issue_is_not_review(self):
        comments = [{"user": {"login": "algora-pbc"}, "body": "Offering a $30 bounty"}]
        result = evaluate(base_issue(comments=80), base_repo(), comments, NOW)
        self.assertNotEqual(result.decision, "review")

    def test_unverified_reward_is_rejected(self):
        result = evaluate(base_issue(body="Bounty $500\nAcceptance Criteria: tests"), base_repo(), [], NOW)
        self.assertEqual(result.decision, "reject")
        self.assertIsNone(result.reward_usd)

    def test_archived_repo_is_rejected(self):
        comments = [{"user": {"login": "algora-pbc"}, "body": "Offering a $100 bounty"}]
        result = evaluate(base_issue(), base_repo(archived=True), comments, NOW)
        self.assertEqual(result.decision, "reject")


if __name__ == "__main__":
    unittest.main()


