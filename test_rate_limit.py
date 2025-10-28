#!/usr/bin/env python3
"""
測試速率限制功能的腳本
"""

import time
from test import RateLimiter

def test_rate_limiter():
    """測試速率限制器"""
    print("🧪 測試速率限制器...")
    
    # 創建速率限制器（測試用，設定較低的限制）
    limiter = RateLimiter(max_requests_per_minute=5)
    
    print("📊 測試：每分鐘最多 5 個請求")
    
    # 測試快速連續請求
    start_time = time.time()
    for i in range(8):  # 嘗試發送 8 個請求
        print(f"發送請求 {i+1}/8...")
        limiter.wait_if_needed()
        print(f"  ✅ 請求 {i+1} 已發送")
    
    end_time = time.time()
    print(f"⏱️ 總耗時：{end_time - start_time:.2f} 秒")
    print("✅ 速率限制測試完成")

if __name__ == "__main__":
    test_rate_limiter()


