import undetected_chromedriver as uc
import os
import time
from selenium.webdriver.common.by import By

def test_profile_consistency():
    """Test untuk buktikan theory profile vs environment inconsistency"""
    
    profiles_dir = 'browser_profiles'
    test_cases = [
        {
            'name': 'Windows Profile - Windows Environment',
            'profile': 'user_3',  # Profile dari QR bot Windows
            'options': get_windows_options()
        },
        {
            'name': 'Windows Profile - Linux Environment', 
            'profile': 'user_3',  # Profile sama, tapi environment Linux
            'options': get_linux_options()
        },
        {
            'name': 'Fresh Profile - Linux Environment',
            'profile': 'fresh_test',  # Profile baru
            'options': get_linux_options()
        }
    ]
    
    for test_case in test_cases:
        print(f"\n🧪 TEST: {test_case['name']}")
        test_single_profile(test_case['profile'], test_case['options'])

def get_windows_options():
    """Options untuk environment Windows"""
    options = uc.ChromeOptions()
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
    options.add_argument('--window-size=1920,1080')
    return options

def get_linux_options():
    """Options untuk environment Linux"""  
    options = uc.ChromeOptions()
    options.add_argument('--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
    options.add_argument('--window-size=1920,1080')
    return options

def test_single_profile(profile_name, username_tiktok):
    """Test single profile scenario"""
    PROFILES_DIR = 'browser_profiles'
    os.makedirs(PROFILES_DIR, exist_ok=True)
    print(f"Menggunakan path profil peramban: {profile_name}")
    profile_path = os.path.join('browser_profiles', profile_name)
    
    options = uc.ChromeOptions()
    options.add_argument(f'--user-data-dir={profile_path}')
    
    driver = uc.Chrome(options=options)
    
    try:
        # Navigate ke TikTok
        driver.get(f"https://www.tiktok.com/@{username_tiktok}")
        time.sleep(5)
        
        # Check captcha
        if check_captcha(driver):
            print("🔴 RESULT: CAPTCHA DETECTED")
        else:
            print("✅ RESULT: NO CAPTCHA")
            
        # Check login status
        login_status = check_login_status(driver)
        print(f"🔐 LOGIN STATUS: {login_status}")
        
    finally:
        driver.quit()

def check_captcha(driver):
    """Check jika captcha muncul"""
    captcha_indicators = [
        '//*[contains(text(), "Verify")]',
        '//*[contains(text(), "CAPTCHA")]',
        '//*[contains(text(), "robot")]'
    ]
    
    for indicator in captcha_indicators:
        try:
            elements = driver.find_elements(By.XPATH, indicator)
            if elements and any(el.is_displayed() for el in elements):
                return True
        except:
            continue
    return False

def check_login_status(driver):
    """Check status login"""
    try:
        # Check untuk elemen logged-in
        profile_elements = driver.find_elements(By.CSS_SELECTOR, '[data-e2e="user-profile"], [class*="avatar"]')
        if profile_elements:
            return "LOGGED_IN"
        else:
            return "NOT_LOGGED_IN"
    except:
        return "UNKNOWN"

if __name__ == "__main__":
    # test_profile_consistency()
    
    # pakai user profile yang sudah ada
    username_tiktok = "cozy_kilo"
    profile_name = "user_3"
    test_single_profile(profile_name, username_tiktok)