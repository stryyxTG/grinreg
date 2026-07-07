from __future__ import annotations

import aiohttp
import asyncio
import logging
import time
import random

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "rucaptcha"):
        self.api_key = api_key
        self.service = service
        self.create_task_url = "https://api.rucaptcha.com/createTask"
        self.get_result_url = "https://api.rucaptcha.com/getTaskResult"

        # Твой прокси (можно заменить на другой)
        self.proxy = {
            "type": "socks5",
            "host": "45.86.3.147",
            "port": 14893,
            "username": "user335792",
            "password": "9etya2",
        }

    async def solve_recaptcha_v2(
        self,
        sitekey: str,
        page_url: str = "https://web.telegram.org",
        timeout: int = 300,
    ) -> str:
        """
        Решает reCAPTCHA v2 через RuCaptcha с максимальной эмуляцией.
        """
        async with aiohttp.ClientSession() as session:
            # Список методов для перебора
            methods = [
                self._solve_with_params(session, sitekey, page_url, "RecaptchaV2Task", timeout),
                self._solve_with_params(session, sitekey, page_url, "RecaptchaV2EnterpriseTask", timeout),
            ]

            for method in methods:
                try:
                    return await method
                except Exception as e:
                    logger.warning(f"Метод не сработал: {e}")
                    await asyncio.sleep(3)

            raise Exception("Не удалось решить капчу ни одним методом")

    async def _solve_with_params(
        self,
        session: aiohttp.ClientSession,
        sitekey: str,
        page_url: str,
        task_type: str,
        timeout: int,
    ) -> str:
        """Решает капчу с максимальными параметрами эмуляции."""
        # Реалистичный User-Agent
        user_agent = random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ])

        # Реалистичные cookies
        cookies = (
            "stel_web_auth=; "
            "tg_web_session=; "
            "device_id=; "
            "ip_country=; "
            "lang=en; "
            "theme=dark; "
            "webm=1; "
            "webp=1; "
            f"_ga=GA1.2.{random.randint(100000, 999999)}.{int(time.time())}; "
            f"_gid=GA1.2.{random.randint(100000, 999999)}.{int(time.time())}"
        )

        # Формируем задачу
        task_data = {
            "type": task_type,
            "websiteURL": page_url,
            "websiteKey": sitekey,
            "isInvisible": False,
            "proxyType": self.proxy["type"],
            "proxyAddress": self.proxy["host"],
            "proxyPort": self.proxy["port"],
            "proxyLogin": self.proxy["username"],
            "proxyPassword": self.proxy["password"],
            "userAgent": user_agent,
            "cookies": cookies,
        }

        # Для Enterprise добавляем параметры
        if "Enterprise" in task_type:
            task_data["enterprise"] = True
            task_data["apiDomain"] = "google.com"

        task_payload = {
            "clientKey": self.api_key,
            "task": task_data,
            "softId": 3898,
            "languagePool": "en",
        }

        logger.info(f"Отправка капчи с методом {task_type}")

        async with session.post(self.create_task_url, json=task_payload) as resp:
            result = await resp.json()
            logger.info(f"Ответ createTask ({task_type}): {result}")

            if result.get("errorId", 0) != 0:
                error_desc = result.get("errorDescription", "Unknown error")
                raise Exception(f"Ошибка RuCaptcha: {error_desc}")

            task_id = result.get("taskId")
            if not task_id:
                raise Exception("RuCaptcha не вернул taskId")

            logger.info(f"Задача создана, taskId: {task_id} ({task_type})")

        # Ожидаем результат
        start_time = time.time()
        attempts = 0

        while time.time() - start_time < timeout:
            await asyncio.sleep(3)
            attempts += 1

            result_payload = {
                "clientKey": self.api_key,
                "taskId": task_id,
            }

            async with session.post(self.get_result_url, json=result_payload) as resp:
                result = await resp.json()
                logger.debug(f"Попытка {attempts} ({task_type}): {result}")

                if result.get("errorId", 0) != 0:
                    error_desc = result.get("errorDescription", "Unknown error")
                    raise Exception(f"Ошибка RuCaptcha: {error_desc}")

                status = result.get("status")
                if status == "ready":
                    token = result.get("solution", {}).get("gRecaptchaResponse")
                    if token:
                        logger.info(f"✅ Капча решена! ({task_type})")
                        return token
                    raise Exception("Нет токена")

                elif status == "processing":
                    if attempts % 5 == 0:
                        logger.info(f"Ожидаем... попытка {attempts} ({task_type})")
                    continue
                else:
                    raise Exception(f"Неизвестный статус: {status}")

        raise TimeoutError(f"Таймаут {timeout}с ({task_type})")