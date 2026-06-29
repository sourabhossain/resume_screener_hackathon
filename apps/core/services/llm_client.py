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

    CACHE_TIMEOUT = 3600
    CACHE_VERSION = "v2"

    REQUEST_TIMEOUT = 60
    MAX_RETRIES = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @staticmethod
    def _is_reasoning_model(model: str) -> bool:
        """
        GPT-5 and the o-series are reasoning models that ONLY accept the default
        sampling temperature (1.0). Sending temperature=0.0 to them returns a
        hard 400 ("Unsupported value: temperature"), which would break every
        screening call. For those models we must omit the temperature kwarg and
        rely on structured output / seeds for determinism instead.
        """
        m = (model or "").lower()
        return m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")

    def __init__(self):
        if self._llm is None:
            api_key = settings.OPENAI_API_KEY
            model = getattr(settings, 'OPENAI_MODEL', 'gpt-5-nano-2025-08-07')
            self._model = model

            if not api_key:
                logger.warning("OPENAI_API_KEY not configured")
                return

            common_kwargs = dict(
                model=model,
                api_key=api_key,
                timeout=self.REQUEST_TIMEOUT,
                max_retries=self.MAX_RETRIES,
            )
            if not self._is_reasoning_model(model):
                common_kwargs["temperature"] = 0.0

            self._llm = ChatOpenAI(**common_kwargs)

            self._llm_json = ChatOpenAI(
                **common_kwargs,
                model_kwargs={"response_format": {"type": "json_object"}}
            )

            logger.info(
                "LLMClient initialized with model: %s (reasoning=%s)",
                model, self._is_reasoning_model(model),
            )

    def _get_cache_key(self, prompt: str) -> str:
        """
        Generate cache key from prompt, scoped to the model id and a cache
        version so a model swap or prompt change never serves stale outputs.
        """
        model = getattr(self, '_model', 'unknown')
        digest = hashlib.md5(prompt.encode()).hexdigest()
        return f"llm_cache_{self.CACHE_VERSION}_{model}_{digest}"
    
    _llm_retry = retry(
        retry=retry_if_exception_type(
            (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError, JSONDecodeError)
        ),
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=4, max=30),
        reraise=True,
    )

    @_llm_retry
    def invoke_json(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> Dict[str, Any]:
        """
        Invoke LLM and return parsed JSON response.
        Uses caching to avoid duplicate API calls.
        
        Args:
            prompt: The user prompt
            system_prompt: The system prompt
            
        Returns:
            Parsed JSON response as dictionary
        """
        if not self._llm_json:
            raise RuntimeError("LLM not initialized. Check OPENAI_API_KEY.")
        
        cache_key = self._get_cache_key(f"{system_prompt}:{prompt}")
        cached = cache.get(cache_key)
        if cached:
            logger.debug("LLM cache hit")
            return cached

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt)
        ]
        
        response = self._llm_json.invoke(messages)
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
