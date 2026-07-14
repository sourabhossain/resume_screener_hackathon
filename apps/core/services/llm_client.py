"""
OpenAI LLM Client with caching and retry logic.
"""
import hashlib
import json
import logging
from typing import Dict, Any

from django.conf import settings
from django.core.cache import cache
from json import JSONDecodeError
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Singleton LLM client with caching and retry logic.
    Uses the OpenAI model configured via settings.OPENAI_MODEL.
    """
    
    _instance = None
    _llm = None
    _llm_json = None
    _llm_json_minimal = None

    CACHE_TIMEOUT = 3600

    # Per-call ceiling so a hung OpenAI request can't pin a screening worker
    # forever. gpt-5-nano is a reasoning model and can take 30-50s on a large
    # resume, so 30s was too tight and caused spurious timeout failures; 60s
    # lets a slow-but-valid call finish. The Celery soft_time_limit (180s) covers
    # the whole 3-4 call pipeline.
    REQUEST_TIMEOUT = 60  # seconds
    # We already retry transient errors ourselves via tenacity below; disable
    # the SDK's own retries so we don't get retries-on-retries (timeout blowup).
    MAX_RETRIES = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._llm is None:
            api_key = settings.OPENAI_API_KEY
            model = getattr(settings, 'OPENAI_MODEL', 'gpt-5-nano-2025-08-07')
            
            if not api_key:
                logger.warning("OPENAI_API_KEY not configured")
                return
            
            self._llm = ChatOpenAI(
                model=model,
                temperature=0.0,
                api_key=api_key,
                timeout=self.REQUEST_TIMEOUT,
                max_retries=self.MAX_RETRIES,
            )

            self._llm_json = ChatOpenAI(
                model=model,
                temperature=0.0,
                api_key=api_key,
                timeout=self.REQUEST_TIMEOUT,
                max_retries=self.MAX_RETRIES,
                model_kwargs={"response_format": {"type": "json_object"}}
            )

            # Extraction is a retrieval task (pull name/skills/dates out of the
            # resume), not a judgment task, so it doesn't need the model's default
            # reasoning budget. reasoning_effort='minimal' cuts the per-call latency
            # that was making extraction blow past REQUEST_TIMEOUT. Scoring stays on
            # the default client above so match/score quality is unchanged.
            # Passed as a top-level kwarg (not model_kwargs): it's a declared field
            # on ChatOpenAI, so nesting it in model_kwargs triggers a warning and is
            # ambiguous.
            self._llm_json_minimal = ChatOpenAI(
                model=model,
                temperature=0.0,
                api_key=api_key,
                timeout=self.REQUEST_TIMEOUT,
                max_retries=self.MAX_RETRIES,
                reasoning_effort="minimal",
                model_kwargs={"response_format": {"type": "json_object"}},
            )

            logger.info(f"LLMClient initialized with model: {model}")
    
    def _get_cache_key(self, prompt: str) -> str:
        """Generate cache key from prompt."""
        return f"llm_cache_{hashlib.md5(prompt.encode()).hexdigest()}"
    
    # Transient OpenAI / network errors: backoff; reraise so logs show the real exception (not RetryError)
    # JSONDecodeError included because LLMs occasionally return malformed JSON despite json_object format
    _llm_retry = retry(
        retry=retry_if_exception_type(
            (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError, JSONDecodeError)
        ),
        # 2 attempts (was 3): with a 60s per-call timeout, 3 retries could exceed
        # the pipeline's Celery budget; 2 still covers a transient blip.
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=4, max=30),
        reraise=True,
    )

    @_llm_retry
    def invoke_json(self, prompt: str, system_prompt: str = "You are a helpful assistant.", fast: bool = False) -> Dict[str, Any]:
        """
        Invoke LLM and return parsed JSON response.
        Uses caching to avoid duplicate API calls.

        Args:
            prompt: The user prompt
            system_prompt: The system prompt
            fast: Use the minimal-reasoning client (for retrieval-style calls like
                  extraction where the default reasoning budget just adds latency).

        Returns:
            Parsed JSON response as dictionary
        """
        llm = self._llm_json_minimal if fast else self._llm_json
        if not llm:
            raise RuntimeError("LLM not initialized. Check OPENAI_API_KEY.")

        # 'min:' namespaces the fast cache so minimal- and default-effort responses
        # for the same prompt never collide.
        cache_key = self._get_cache_key(f"{'min:' if fast else ''}{system_prompt}:{prompt}")
        cached = cache.get(cache_key)
        if cached:
            logger.debug("LLM cache hit")
            return cached


        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]

        response = llm.invoke(messages)
        result = json.loads(response.content)
        

        cache.set(cache_key, result, self.CACHE_TIMEOUT)
        
        return result
    
    @_llm_retry
    def invoke_text(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        """
        Invoke LLM and return text response.
        Uses caching to avoid duplicate API calls.
        
        Args:
            prompt: The user prompt
            system_prompt: The system prompt
            
        Returns:
            Text response
        """
        if not self._llm:
            raise RuntimeError("LLM not initialized. Check OPENAI_API_KEY.")
        
        cache_key = self._get_cache_key(f"text:{system_prompt}:{prompt}")
        cached = cache.get(cache_key)
        if cached:
            logger.debug("LLM text cache hit")
            return cached
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        response = self._llm.invoke(messages)
        result = response.content
        

        cache.set(cache_key, result, self.CACHE_TIMEOUT)
        
        return result



llm_client = LLMClient()
