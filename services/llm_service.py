"""
LLM integration service — two-pass note generation with quality review.

Supports multiple providers: OpenAI, Anthropic, NVIDIA (free), OpenRouter.
Implements the required draft → review architecture with AI quality checks.
"""

import json
from typing import Any, Dict, Optional

import httpx

from utils.logger import logger
from utils.jitter import apply_all_jitter


# ── Provider configurations ───────────────────────────────────

_PROVIDER_CONFIGS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "chat_endpoint": "/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "chat_endpoint": "/messages",
        "auth_header": "x-api-key",
        "auth_prefix": "",
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "chat_endpoint": "/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "chat_endpoint": "/chat/completions",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}


class LLMService:
    """
    Two-pass LLM service for personalized note and comment generation.

    Pass 1 (Draft): Generate initial personalized content
    Pass 2 (Review): AI quality check — verify personalization, length, tone
    Post-processing: Apply human-like jitter for anti-detection
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: str = "",
        temperature: float = 0.7,
        review_temperature: float = 0.3,
        default_char_limit: int = 300,
        nvidia_base_url: str = "",
        openrouter_base_url: str = "",
    ):
        self._provider = provider.lower()
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._review_temperature = review_temperature
        self._default_char_limit = default_char_limit

        # Override base URLs if provided
        if nvidia_base_url and self._provider == "nvidia":
            _PROVIDER_CONFIGS["nvidia"]["base_url"] = nvidia_base_url
        if openrouter_base_url and self._provider == "openrouter":
            _PROVIDER_CONFIGS["openrouter"]["base_url"] = openrouter_base_url

        if self._provider not in _PROVIDER_CONFIGS:
            raise ValueError(
                f"Unsupported LLM provider: {self._provider}. "
                f"Supported: {list(_PROVIDER_CONFIGS.keys())}"
            )

        logger.info(f"LLM Service initialized — provider={self._provider}, model={self._model}")

    # ── Core API call ─────────────────────────────────────────

    async def _call_llm(self, system_prompt: str, user_prompt: str,
                        temperature: Optional[float] = None) -> str:
        """
        Make an LLM API call.

        Handles provider-specific request/response formats.
        """
        config = _PROVIDER_CONFIGS[self._provider]
        temp = temperature if temperature is not None else self._temperature

        if self._provider == "anthropic":
            return await self._call_anthropic(system_prompt, user_prompt, temp)

        # OpenAI-compatible API (OpenAI, NVIDIA, OpenRouter)
        url = f"{config['base_url']}{config['chat_endpoint']}"
        headers = {
            config["auth_header"]: f"{config['auth_prefix']}{self._api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter-specific headers
        if self._provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/linkedin-outreach"
            headers["X-Title"] = "LinkedIn Outreach Automation"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temp,
            "max_tokens": 500,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"LLM response ({len(content)} chars): {content[:100]}...")
        return content

    async def _call_anthropic(self, system_prompt: str, user_prompt: str,
                              temperature: float) -> str:
        """Handle Anthropic's Messages API format."""
        config = _PROVIDER_CONFIGS["anthropic"]
        url = f"{config['base_url']}{config['chat_endpoint']}"

        headers = {
            config["auth_header"]: f"{config['auth_prefix']}{self._api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": self._model,
            "max_tokens": 500,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content = data["content"][0]["text"].strip()
        logger.debug(f"Anthropic response ({len(content)} chars): {content[:100]}...")
        return content

    # ── Note Generation (Two-Pass) ────────────────────────────

    async def generate_note(
        self,
        profile_context: Dict[str, Any],
        sender_context: str = "",
        sender_name: str = "",
        char_limit: int = 0,
    ) -> Dict[str, str]:
        """
        Generate a personalized LinkedIn connection note using two-pass architecture.

        Pass 1: Draft — Generate initial note from profile context
        Pass 2: Review — AI quality check and refinement
        Post-processing: Jitter — Apply human-like variations

        Args:
            profile_context: Extracted profile data (name, headline, role, etc.)
            sender_context: Brief description of the sender (from config)
            sender_name: Name of the person sending the request
            char_limit: Max characters (0 = use default)

        Returns:
            Dict with 'draft', 'reviewed', and 'final' note versions.
        """
        limit = char_limit or self._default_char_limit
        name = profile_context.get("name", "there")

        # ── Pass 1: Draft Generation ──
        logger.info(f"📝 Pass 1: Generating draft note for {name}...")

        draft_system = (
            "You are a professional networking assistant. Your task is to generate "
            "a personalized LinkedIn connection request note.\n\n"
            "RULES:\n"
            f"- The note MUST be {limit} characters or fewer (this is a hard limit)\n"
            "- Reference something SPECIFIC from the person's profile (their role, "
            "a project, their headline, recent activity)\n"
            "- Sound warm, genuine, and human — NOT like a template or sales pitch\n"
            "- Start with a greeting using their first name\n"
            "- State a clear, authentic reason for connecting\n"
            "- Do NOT use buzzwords like 'synergy', 'leverage', 'ecosystem'\n"
            "- Do NOT be overly flattering or sycophantic\n"
            "- Output ONLY the note text, nothing else"
        )

        context_parts = []
        if profile_context.get("name"):
            context_parts.append(f"Name: {profile_context['name']}")
        if profile_context.get("headline"):
            context_parts.append(f"Headline: {profile_context['headline']}")
        if profile_context.get("current_role"):
            context_parts.append(f"Current Role: {profile_context['current_role']}")
        if profile_context.get("company"):
            context_parts.append(f"Company: {profile_context['company']}")
        if profile_context.get("about_snippet"):
            context_parts.append(f"About: {profile_context['about_snippet']}")
        if profile_context.get("recent_posts"):
            posts_text = "; ".join(profile_context["recent_posts"][:2])
            context_parts.append(f"Recent Activity: {posts_text}")
        if profile_context.get("mutual_connections"):
            context_parts.append(
                f"Mutual Connections: {profile_context['mutual_connections']}"
            )

        profile_text = "\n".join(context_parts)

        draft_user = (
            f"Generate a connection note for this person:\n\n"
            f"{profile_text}\n\n"
        )
        if sender_context:
            draft_user += f"About the sender: {sender_context}\n"
        if sender_name:
            draft_user += f"Sender's name: {sender_name}\n"
        draft_user += f"\nCharacter limit: {limit} characters"

        draft = await self._call_llm(draft_system, draft_user, self._temperature)

        # Ensure draft is within limit
        if len(draft) > limit:
            draft = draft[:limit].rsplit(" ", 1)[0].rstrip(".,!? ") + "."

        logger.info(f"  Draft ({len(draft)} chars): {draft}")

        # ── Pass 2: Review & Refine ──
        logger.info(f"🔍 Pass 2: AI review pass for {name}...")

        review_system = (
            "You are a quality reviewer for LinkedIn connection notes. "
            "Review the draft note against these criteria:\n\n"
            "1. LENGTH: Must be {limit} characters or fewer\n"
            "2. PERSONALIZATION: Must reference something specific about the person, "
            "not be generic\n"
            "3. TONE: Must sound warm, human, and genuine — not robotic or salesy\n"
            "4. GRAMMAR: No spelling or grammar errors\n"
            "5. APPROPRIATENESS: Professional and respectful\n"
            "6. AUTHENTICITY: Should read like a real person wrote it\n\n"
            "If the note meets ALL criteria, return it as-is.\n"
            "If ANY criterion is not met, rewrite the note to fix the issues.\n"
            "Output ONLY the final note text, nothing else."
        ).format(limit=limit)

        review_user = (
            f"Review this LinkedIn connection note draft:\n\n"
            f"\"{draft}\"\n\n"
            f"Profile context for reference:\n{profile_text}\n\n"
            f"Character limit: {limit} characters"
        )

        reviewed = await self._call_llm(review_system, review_user, self._review_temperature)

        # Ensure reviewed is within limit
        if len(reviewed) > limit:
            reviewed = reviewed[:limit].rsplit(" ", 1)[0].rstrip(".,!? ") + "."

        logger.info(f"  Reviewed ({len(reviewed)} chars): {reviewed}")

        # ── Post-processing: Jitter ──
        first_name = name.split()[0] if name else None
        final = apply_all_jitter(reviewed, name=first_name, char_limit=limit)

        logger.info(f"  Final ({len(final)} chars): {final}")

        return {
            "draft": draft,
            "reviewed": reviewed,
            "final": final,
        }

    # ── Comment Generation (Two-Pass) ─────────────────────────

    async def generate_comment(
        self,
        post_text: str,
        profile_context: Dict[str, Any],
        sender_name: str = "",
    ) -> Dict[str, str]:
        """
        Generate a thoughtful comment on a LinkedIn post using two-pass architecture.

        Pass 1: Draft — Generate relevant comment
        Pass 2: Review — AI quality check

        Args:
            post_text: The text of the LinkedIn post to comment on.
            profile_context: Extracted profile data of the post author.
            sender_name: Name of the commenter.

        Returns:
            Dict with 'draft' and 'final' comment versions.
        """
        author_name = profile_context.get("name", "the author")

        # ── Pass 1: Draft Comment ──
        logger.info(f"💬 Pass 1: Generating comment for {author_name}'s post...")

        draft_system = (
            "You are a thoughtful professional commenter on LinkedIn. "
            "Generate a genuine, relevant comment on the following post.\n\n"
            "RULES:\n"
            "- Keep it between 50-200 characters\n"
            "- Be specific to the post content — reference actual points made\n"
            "- Add value: share a brief insight, ask a thoughtful question, "
            "or express genuine appreciation with specifics\n"
            "- Sound like a real person, not a bot\n"
            "- Do NOT be overly effusive or use excessive exclamation marks\n"
            "- Do NOT use phrases like 'Great post!' or 'Thanks for sharing!' alone\n"
            "- Output ONLY the comment text, nothing else"
        )

        draft_user = (
            f"Post by {author_name}:\n\"{post_text[:500]}\"\n\n"
            f"Generate a thoughtful comment."
        )
        if sender_name:
            draft_user += f"\nCommenter's name: {sender_name}"

        draft = await self._call_llm(draft_system, draft_user, self._temperature)
        logger.info(f"  Comment draft ({len(draft)} chars): {draft}")

        # ── Pass 2: Review Comment ──
        logger.info(f"🔍 Pass 2: Reviewing comment quality...")

        review_system = (
            "You are a quality reviewer for LinkedIn comments. "
            "Review this comment against these criteria:\n\n"
            "1. RELEVANCE: Must relate specifically to the post content\n"
            "2. VALUE: Must add something meaningful (insight, question, appreciation)\n"
            "3. TONE: Professional, genuine, not sycophantic\n"
            "4. LENGTH: Between 50-200 characters\n"
            "5. AUTHENTICITY: Reads like a real person wrote it\n\n"
            "If the comment meets ALL criteria, return it as-is.\n"
            "If ANY criterion is not met, rewrite it.\n"
            "Output ONLY the final comment text, nothing else."
        )

        review_user = (
            f"Review this comment:\n\"{draft}\"\n\n"
            f"Original post:\n\"{post_text[:500]}\""
        )

        final = await self._call_llm(review_system, review_user, self._review_temperature)
        logger.info(f"  Comment final ({len(final)} chars): {final}")

        return {
            "draft": draft,
            "final": final,
        }

    # ── Health Check ──────────────────────────────────────────

    async def health_check(self) -> bool:
        """Verify LLM API connectivity with a simple test call."""
        try:
            response = await self._call_llm(
                "You are a helpful assistant.",
                "Reply with just 'OK'.",
                temperature=0.0,
            )
            ok = len(response) > 0
            if ok:
                logger.info(f"✅ LLM health check passed ({self._provider}/{self._model})")
            return ok
        except Exception as e:
            logger.error(f"❌ LLM health check failed: {e}")
            return False
