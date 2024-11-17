# 標準庫
import json
import time
import re
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
import urllib.request

# Selenium
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

def create_driver():
    """
    初始化瀏覽器設定並返回 Chrome WebDriver (driver)
    """
    options = Options()
    
    # 基本設定
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0')
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--mute-audio')
    options.add_argument("--window-size=1920x1080")
    
    # 啟用 Network Logging
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    # 隱藏不必要的終端機輸出
    options.add_argument('--log-level=1')
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
    
    return webdriver.Edge(options = options)

def cookie_login(driver, cookie_file):
    """
        使用cookie登入twitter(auth_token)
    """
    driver.get('https://x.com')

    # 載入保存的 cookies
    with open(cookie_file, 'r') as f:
        cookies = json.load(f)

    for cookie in cookies:
        driver.add_cookie(cookie)

    driver.refresh()

    return driver


class FFMPEG():
    def __init__(self) -> None:
        pass

    def merge_m3u8(self, input_filepath, output_filepath):
        # 如果 FFmpeg 不在 PATH 中，指定完整路徑
        # r'C:\Program Files\FFMPEG\bin\ffmpeg.exe'
        command = [
            'ffmpeg',
            '-i', input_filepath,
            '-c', 'copy',
            output_filepath
        ]

        try:
            # 執行命令
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        except subprocess.CalledProcessError as e:
            print("FFmpeg命令執行失敗")
            print("錯誤：", e.stderr)


    def merge_video_audio(self, video_filepath, audio_filepath, output_filepath):
        command = [
            'ffmpeg',
            '-i', video_filepath,  # 視訊輸入
            '-i', audio_filepath,  # 音訊輸入
            '-c:v', 'copy',        # 複製視訊編碼（不重新編碼）
            '-c:a', 'aac',         # 使用 AAC 編碼音訊
            '-strict', 'experimental',  # 允許實驗性的 AAC 編碼器
            '-y',                  # 覆蓋已存在的輸出文件
            output_filepath
        ]
        
        try:
            # 執行命令
            subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
        except subprocess.CalledProcessError as e:
            print("FFmpeg 命令執行失敗")
            print("錯誤：", e.stderr)


class TwitterVideoDownloader():
    def __init__(self, driver):
        self.BASE_URL = 'https://video.twimg.com'
        self.ffmpeg = FFMPEG()

        self.driver = driver


    def extract_urls(self, text):
        """
            找出結尾是.mp4或.m4s的URL
        """
        # pattern = re.compile(r'https?:\/\/[^\s"]+?\.(?:mp4|m4s)')
        pattern = re.compile(r'[^\"\s]+(?:mp4|m4s)')
        
        urls = pattern.findall(text)
        return urls

    def get_m3u8_format(self, url):
        """
            分析m3u8檔案中的網址，返回檔案類型及影片id
            url = "/ext_tw_video/1815031743948394496/pu/vid/avc1/0/0/1080x1080/F0_cwFh9VRykKpeG.mp4"
            parts[-2] = 1080x1080
            parts[2] = 1815031743948394496
        """
        
        if 'aud' in url:
            format = 'audio'
        elif 'vid' in url:
            format = 'video'    
        else:
            return None          
        
        # 影片大小
        # size = url.split('/')[-2]
        video_id = url.split('/')[2]

        # return video_id, format, size
        return video_id, format

    def parse_m3u8_urls(self, url, timeout = 10, poll_frequency = 0.5):
        self.driver.get(url)
        # self.driver.refresh()

        m3u8_urls = []
        start_time = time.time()

        while time.time() - start_time < timeout:
            # 獲取瀏覽器日誌
            logs = self.driver.get_log('performance')

            for log in logs:
                message = json.loads(log['message'])['message']
                if 'Network.responseReceived' in message['method']:
                    try:
                        response_url = message['params']['response']['url']
                        if response_url.endswith('.m3u8'):
                            m3u8_urls.append(response_url)
                    except KeyError:
                        continue

            if m3u8_urls:
                return list(OrderedDict.fromkeys(m3u8_urls))

            # 等待一段時間後重新尋找
            time.sleep(poll_frequency)

        return m3u8_urls
    

    def process_m3u8(self, m3u8_filepath, download_folder):
        with open(m3u8_filepath, 'r') as f:
            content = f.read()

        segment_urls = self.extract_urls(content)        

        # 下載分段檔案        
        # print('-'*150)
        for i, url in enumerate(segment_urls):
            complete_url = f"{self.BASE_URL}{url}"
            filename = str(Path(url).name) # xxx.m4s or xxx.mp4
            output_filepath = download_folder / filename
            urllib.request.urlretrieve(complete_url, output_filepath)
            
            # 取代m3u8中的url
            content = content.replace(url, filename)            
            print(f"{i+1:2d}/{len(segment_urls):2d} : {url}", end='\r')


        # 寫入網址更新為檔案名稱的m3u8檔案
        video_id, m3u8_format = self.get_m3u8_format(segment_urls[0])    
        m3u8_filepath = download_folder / f'{video_id}_{m3u8_format}.m3u8'
        with open(m3u8_filepath, 'w') as f:
            f.write(content)
        
        # 合併片段
        output_filepath = download_folder / f'{video_id}_{m3u8_format}.mp4'
        self.ffmpeg.merge_m3u8(m3u8_filepath, output_filepath)

        return video_id


    def download(self, tweet_url, m3u8_urls = None, folder = None):
        tweet_status = Path(tweet_url).name
        tweet_username = tweet_url.split('/')[-3]
        download_folder = Path(folder) / Path(Path(tweet_url).name) # 1736361975469441511
        download_folder.mkdir(exist_ok = True)

        # 取得.m3u8檔案連結並下載
        if not m3u8_urls:  
            m3u8_urls = self.parse_m3u8_urls(tweet_url)  

        m3u8_filepaths = []
        for url in m3u8_urls:
            output_filepath = download_folder / Path(url).name # folder / NYf5OzT2LbATEvbg.m3u8    
            urllib.request.urlretrieve(url, output_filepath)
            m3u8_filepaths.append(output_filepath)

        video_ids = set()
        for m3u8_filepath in m3u8_filepaths:
            video_id = self.process_m3u8(m3u8_filepath, download_folder)
            video_ids.add(video_id)
            
        # 合併影片檔和音訊檔
        for _, video_id in enumerate(list(video_ids)):
            video_file = download_folder / f'{video_id}_video.mp4'
            audio_file = download_folder / f'{video_id}_audio.mp4'

            output_file = f"{folder}/twi@{tweet_username}_{tweet_status}.mp4"

            self.ffmpeg.merge_video_audio(video_file, audio_file, output_file)            

        shutil.rmtree(download_folder)

        print(f"\n影片下載成功 : {output_file}")
        print("刪除所有暫存檔案")
        print('-'*150)

if __name__=="__main__":
    tweet_url = "https://x.com/kchsom/status/1834424928893829181"

    # 初始化瀏覽器
    driver = create_driver()
    cookie_file = "twitter_auth_cookies.json"
    cookie_login(driver, cookie_file)

    twi_downloader = TwitterVideoDownloader(driver)
    # m3u8_urls = twi_downloader.parse_m3u8_urls(tweet_url)
    # print(m3u8_urls)
    twi_downloader.download(tweet_url, ['https://video.twimg.com/ext_tw_video/1842120532138848256/pu/pl/avc1/720x720/PXOm6yhsljTavjuU.m3u8', 'https://video.twimg.com/ext_tw_video/1842120532138848256/pu/pl/mp4a/128000/JKbMuOXAv2UYZG_R.m3u8'], folder= '1834424928893829181')

    driver.quit()
