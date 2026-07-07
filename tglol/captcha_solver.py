from __future__ import annotations

import aiohttp
import asyncio
import logging

logger = logging.getLogger(__name__)


class CaptchaSolver:
    def __init__(self, api_key: str, service: str = "2captcha"):
        self.api_key = api_key
        self.service = service
        
        if service in ("2captcha", "rucaptcha"):
            self.submit_url = f"https://{service}.com/in.php"
            self.result_url = f"https://{service}.com/res.php"
        elif service == "capsolver":
            self.submit_url = "https://api.capsolver.com/createTask"
            self.result_url = "https://api.capsolver.com/getTaskResult"
        else:
            raise ValueError("service должен быть '2captcha', 'rucaptcha' или 'capsolver'")
    
    async def solve_recaptcha_v2(self, sitekey: str, page_url: str = "https://telegram.org", timeout: int = 120) -> str:
        if self.service in ("2captcha", "rucaptcha"):
            return await self._solve_standard(sitekey, page_url, timeout)
        else:
            return await self._solve_capsolver(sitekey, page_url, timeout)
    
    async def _solve_standard(self, sitekey: str, page_url: str, timeout: int) -> str:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.submit_url,
                data={
                    'key': self.api_key,
                    'method': 'userrecaptcha',
                    'googlekey': sitekey,
                    'pageurl': page_url,
                    'json': 1
                }
            ) as resp:
                result = await resp.json()
                if result.get('status') != 1:
                    raise Exception(f"Ошибка {self.service}: {result.get('request', 'Unknown error')}")
                captcha_id = result['request']
                logger.info(f"Капча отправлена в {self.service}, ID: {captcha_id}")
            
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                await asyncio.sleep(2)
                async with session.get(
                    self.result_url,
                    params={
                        'key': self.api_key,
                        'action': 'get',
                        'id': captcha_id,
                        'json': 1
                    }
                ) as resp:
                    result = await resp.json()
                    if result.get('status') == 1:
                        token = result['request']
                        logger.info(f"Капча решена! Токен: {token[:30]}...")
                        return token
                    if result.get('request') == 'CAPCHA_NOT_READY':
                        continue
                    raise Exception(f"Ошибка {self.service}: {result.get('request', 'Unknown error')}")
            
            raise TimeoutError(f"Время ожидания решения капчи истекло ({timeout}с)")
    
    async def _solve_capsolver(self, sitekey: str, page_url: str, timeout: int) -> str:
        async with aiohttp.ClientSession() as session:
            payload = {
                "clientKey": self.api_key,
                "task": {
                    "type": "RecaptchaV2TaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey
                }
            }
            async with session.post(self.submit_url, json=payload) as resp:
                result = await resp.json()
                if result.get('errorId') != 0:
                    raise Exception(f"Ошибка CapSolver: {result.get('errorDescription', 'Unknown error')}")
                task_id = result['taskId']
                logger.info(f"Капча отправлена в CapSolver, ID: {task_id}")
            
            start_time = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - start_time < timeout:
                await asyncio.sleep(2)
                payload = {"clientKey": self.api_key, "taskId": task_id}
                async with session.post(self.result_url, json=payload) as resp:
                    result = await resp.json()
                    if result.get('status') == 'ready':
                        token = result['solution']['gRecaptchaResponse']
                        logger.info(f"Капча решена! Токен: {token[:30]}...")
                        return token
                    if result.get('status') == 'processing':
                        continue
                    raise Exception(f"Ошибка CapSolver: {result.get('errorDescription', 'Unknown error')}")
            
            raise TimeoutError(f"Время ожидания решения капчи истекло ({timeout}с)")