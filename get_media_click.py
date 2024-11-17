# 標準庫
import time
import random
import logging
import json
import re
from pathlib import Path
from datetime import datetime, timezone
import urllib.request

# Pandas
import pandas as pd

# Selenium 相關導入
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options       
# from selenium.webdriver.edge.options import Options  
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# 自定義模組導入
from twitter_video_downloader import TwitterVideoDownloader


def create_driver():
    """
    初始化瀏覽器設定並返回 Chrome WebDriver (driver)
    """
    options = Options()
    
    # 基本設定
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0')
    # options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('--disable-extensions')
    options.add_argument('--mute-audio')
    options.add_argument("--window-size=1920x1080")
    
    # 啟用 Network Logging
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    # 隱藏不必要的終端機輸出
    options.add_argument('--log-level=1')
    options.add_experimental_option('excludeSwitches', ['enable-automation', 'enable-logging'])
    
    return webdriver.Chrome(options = options)
    # return webdriver.Edge(options = options)


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


class TwitterMediaLinkExtractor():
    def __init__(self, driver):
        # xpath with './/' 相對路徑，從當前的element開始尋找
        # xpath with '//' 絕對路徑，從整個html文檔開始尋找
        self.MEDIA_ATAG_XPATH = ".//a[@class='css-175oi2r r-o7ynqc r-6416eg r-1ny4l3l r-1loqt21']"
        self.MEDIA_ENGAGEMENT_XPATH = "//div[@class='css-175oi2r r-1kbdv8c r-18u37iz r-1wtj0ep r-h3s6tt r-10m99ii r-3o4zer']"
        self.TWEET_TIME_XPATH = "//div[@class='css-175oi2r r-1d09ksm r-18u37iz r-1wbh5a2 r-1471scf']//time"        
        self.TEXT_XPATH    = '//div[@class="css-146c3p1 r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-1inkyih r-16dba41 r-bnwqim r-135wba7"]'
        self.MEDIA_INFO_XPATH = ".//div[@class='css-175oi2r r-1awozwy r-k200y r-z2wwpe r-z80fyv r-1777fci r-is05cd r-loe9s5 r-1nlw0im r-trjkob r-u8s1d r-633pao']//span"

        self.VIDEO_XPATH = "//video[@aria-label = '嵌入的影片']"
        self.IMAGE_XPATHS = {
            'image' : "//div[@class='css-175oi2r r-1pi2tsx r-u8s1d r-13qz1uu']//img[@class='css-9pa8cd']",
            'gif'   : "//div[@class='css-175oi2r r-1pi2tsx r-u8s1d r-13qz1uu']//video",
        }

        self.MEDIA_AMOUNT_XPATH = "//div[@class='css-146c3p1 r-dnmrzs r-1udh08x r-3s2u2q r-bcqeeo r-1ttztb7 r-qvutc0 r-37j5jr r-n6v787 r-1cwl3u0 r-16dba41']"

        self.driver = driver
        self.logger = logging.getLogger(__name__)


    def scroll_page(self, scroll_increment):
        script = """
            let currentScroll = window.pageYOffset || document.documentElement.scrollTop;
            let newScroll = currentScroll + arguments[0];
            window.scrollTo(0, newScroll);
            return newScroll;
        """
        return self.driver.execute_script(script, scroll_increment)

    def is_scroll_bottom(self):
        # 獲取當前滾動位置
        scrolled = self.driver.execute_script("return window.pageYOffset;")
        # 獲取視窗高度
        window_height = self.driver.execute_script("return window.innerHeight;")
        # 獲取頁面總高度
        total_height = self.driver.execute_script("return document.body.scrollHeight;")

        # 判斷是否已經滾動到底部
        return scrolled + window_height >= total_height

    def click_next_image(self):
        next_button_xpath = "//button[@aria-label='下一張投影片']"
        try:
            # 使用 WebDriverWait 等待按鈕出現
            next_button = WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.XPATH, next_button_xpath))
            )
            next_button.click()
            return True
        
        except TimeoutException:
            return False
        except NoSuchElementException:
            return False
        except:
            return False
        
    def close_media(self):
        close_button_xpath = "//button[@aria-label='關閉']"
        while True:
            try:
                close_button = WebDriverWait(self.driver, 2).until(
                    EC.presence_of_element_located((By.XPATH, close_button_xpath))
                )
                close_button.click()
                break
            except:
                pass

    def expand_media(self):
        expand_button_xpath = "//button[@aria-label='查看貼文']"      
        try:
            # 使用 WebDriverWait 等待按鈕出現
            expand_button = WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.XPATH, expand_button_xpath))
            )
            expand_button.click()
        except:    
            pass

    def extract_engagement(self, text):
        patterns = {
            'reply'   : r'(\d+) 則回覆',
            'retweet' : r'(\d+) 次轉發',
            'like'    : r'(\d+) 個喜歡',
            'bookmark': r'(\d+) 個書籤',
            'view'    : r'(\d+) 次觀看'
        }

        engagement_dict = {key: 0 for key in patterns}

        # 使用正則表達式填充 engagement 字典
        for key, pattern in patterns.items():
            matched = re.findall(pattern, text)
            if matched:
                engagement_dict[key] = int(matched[0])

        return engagement_dict

    def get_m3u8_urls(self, timeout = 5, poll_frequency = 1):
        video_element = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located((By.XPATH, self.VIDEO_XPATH))
        )        
        video_poster = video_element.get_attribute('poster')
        # poster = 
        # https://pbs.twimg.com/ext_tw_video_thumb/1841962982311391232/pu/img/B6SJCE5HUvguxuhA.jpg
        # https://pbs.twimg.com/ext_tw_video_thumb/1841962982311391232/img/B6SJCE5HUvguxuhA.jpg
        # video_id = video_poster.split('/')[-3] 

        match = re.search(r'/(\d+)/', video_poster)
        video_id = match.group(1)

        m3u8_urls = []
        start_time = time.time()
        while time.time() - start_time < timeout:            
            # 獲取瀏覽器日誌
            logs = self.driver.get_log('performance')
            for log in logs:
                message = json.loads(log['message'])['message']
                try:
                    response_url = message['params']['response']['url']
                    if response_url.endswith('.m3u8') and video_id in response_url:
                        m3u8_urls.append(response_url)
                except KeyError:
                    continue

            if m3u8_urls:
                break

            # 等待一段時間後重新尋找
            time.sleep(poll_frequency)

        return m3u8_urls

    def get_engagement(self):
        engagement_element = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located((By.XPATH, self.MEDIA_ENGAGEMENT_XPATH))
        )
        engagement_text = engagement_element.get_attribute('aria-label')
        engagement = self.extract_engagement(engagement_text)

        return engagement
    
    def get_time(self):
        time_element = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located((By.XPATH, self.TWEET_TIME_XPATH))
        )
        tweet_time = time_element.get_attribute('datetime')

        return tweet_time
    
    def get_text(self):
        try:        
            text_element = WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.XPATH, self.TEXT_XPATH))
            )        
            text = text_element.text
        except:
            return ""

        return text
    
    def get_tweet_url(self):
        a_tag_element = self.media_element.find_element(By.XPATH, self.MEDIA_ATAG_XPATH)
        tweet_url = a_tag_element.get_attribute('href')
        return tweet_url
    

    def get_media_type(self):
        media_info_text = ''
        try:            
            media_info_element = self.media_element.find_element(By.XPATH, self.MEDIA_INFO_XPATH)
            media_info_text = media_info_element.text
        except NoSuchElementException:
            media_info_text = ''

        if ':' in media_info_text:
            media_type = 'video'
        elif media_info_text == 'GIF':
            media_type = 'gif'
        else:
            media_type = 'image'
        
        return media_type


    def get_image_urls(self, media_type):      
        media_link_list = []
        while True:
            is_clicked = self.click_next_image()
            if not is_clicked:
                img_tags = self.driver.find_elements(By.XPATH, self.IMAGE_XPATHS[media_type])
                media_link_list = [img_tag.get_attribute('src') for img_tag in img_tags]                            
                break

        return media_link_list
    
    def get_media_urls(self):        
        if self.media_type == 'video':
            media_link_list = self.get_m3u8_urls()
        else:
            media_link_list = self.get_image_urls(self.media_type)

        return media_link_list

    def get_media_amount(self):
        total_media_amount_element = self.driver.find_element(By.XPATH, self.MEDIA_AMOUNT_XPATH)
        total_media_amount_text = total_media_amount_element.text
        pattern = r'(\d+(?:,\d+)*) 個相片和影片'
        matched = re.findall(pattern, total_media_amount_text)
        total_media_amount = int(matched[0].replace(',', ''))

        return total_media_amount
    
    def get_clicked_media_content(self, li_id):
        media_element_xpath = f'.//li[@id="verticalGridItem-{li_id}-profile-grid-0"]'
        
        # try:
        # 獲取媒體元素
        self.media_element = WebDriverWait(self.driver, 2).until(
            EC.presence_of_element_located((By.XPATH, media_element_xpath))
        )
        self.media_type = self.get_media_type()

        self.media_element.click()
        self.expand_media()

        self.tweet_url = self.get_tweet_url()                              
        tweet_engagement = self.get_engagement()
        tweet_time = self.get_time()
        tweet_text = self.get_text()
        tweet_media_links = self.get_media_urls()
                                        
        self.close_media()    

        content_dict = {
            'url'         : self.tweet_url,
            'status'      : self.tweet_url.split('/')[-3],
            'username'    : self.tweet_url.split('/')[-5], 
            'tweet_time'  : tweet_time, 
            'tweet_text'  : tweet_text,
            'media_links' : tweet_media_links, 
            'media_type'  : self.media_type,
            'reply'       : int(tweet_engagement['reply']),
            'retweet'     : int(tweet_engagement['retweet']),
            'like'        : int(tweet_engagement['like']),
            'bookmark'    : int(tweet_engagement['bookmark']),
            'view'        : int(tweet_engagement['view']),
            'created_time': datetime.now(timezone.utc).isoformat(timespec='seconds')
        }

        return content_dict

    def get_media_content(self, url, tweet_amount = 1, tweet_excel_path = Path("tweets.xlsx"), log_batch_size = 5):
        """獲取媒體頁面(media)上的圖片/影片推文內容"""
        self.driver.get(url)
        time.sleep(1)

        # 
        media_amount = self.get_media_amount()
        if tweet_amount > media_amount:
            tweet_amount = media_amount

        # 獲取 Excel 中最近的推文時間
        latest_tweet_time = "0000-00-00T00:00:00.000Z"    
        if tweet_excel_path.exists():
            df = pd.read_excel(tweet_excel_path)
            # df['tweet_time'] = pd.to_datetime(df['tweet_time'])
            sorted_df = df.sort_values(by = 'tweet_time', ascending = True)
            latest_tweet_time = sorted_df.iloc[-1]['tweet_time']    
            print(f"\033[92m上次獲取推文時間 : {latest_tweet_time}\033[0m")              

        # 
        count = 0
        tweet_content_list = []
        for li_id in range(tweet_amount):
            try:
                print(f"{li_id+1} / {tweet_amount}")
                sleep_time = round(random.uniform(0, 2), 1)
                time.sleep(sleep_time)
                tweet_content_dict = self.get_clicked_media_content(li_id)
                
                if tweet_content_dict['tweet_time'] <= latest_tweet_time:
                    print(f'\033[91m沒有最新的推文了，上次獲取推文時間 : {latest_tweet_time}\033[0m')
                    break

                tweet_content_list.append(tweet_content_dict)

                
                print(f"推文時間 : {tweet_content_dict['tweet_time'][:10]}")
                print(f"推文連結 : {tweet_content_dict['url']}")
                for i in range(len(tweet_content_dict['media_links'])):
                    if i == 0:
                        print(f"媒體連結 : {tweet_content_dict['media_links'][i]}")
                    else:
                        print(f"           {tweet_content_dict['media_links'][i]}")

                print('-'*150)      

                sleep_time = round(random.uniform(1, 3), 1)
                time.sleep(sleep_time)

                count += 1
                if count % log_batch_size == 0:
                    write_tweets_to_xlsx(tweet_content_list[count-log_batch_size:count], tweet_excel_path)
            except:
                # print(f"無法解析推文 li_id : {li_id}")
                print(f'\033[91m[無法解析推文] li_id : {li_id}\033[0m')
                pass

        if count % log_batch_size:
            write_tweets_to_xlsx(tweet_content_list[count - count % log_batch_size:count], tweet_excel_path)
        return tweet_content_list

        # if len(media_link_list) >= tweet_amount or self.is_scroll_bottom():                
        #     break

        # # 執行滾動
        # scroll_amount = str(int(random.uniform(512, 1024))) # random height
        # self.scroll_page(scroll_amount) 


def write_tweets_to_xlsx(tweet_content_list, tweet_excel_path = Path('tweet.xlsx')):
    column_name = ['url', 'status', 'username', 'tweet_time', 'tweet_text', 'media_links', 
                        'media_type', 'reply', 'retweet', 'like', 'bookmark', 'view', 'created_time']
    
    df = pd.DataFrame(tweet_content_list)
    
    # 確保所有列都存在，如果不存在則用NaN填充
    for column in column_name:
        if column not in df.columns:
            df[column] = pd.NA

    # 將多個媒體連結使用", "分開
    df['media_links'] = df['media_links'].apply(lambda x: ', '.join(x) if isinstance(x, list) else x)

    if tweet_excel_path.exists():
        with pd.ExcelWriter(tweet_excel_path, engine = 'openpyxl', mode = 'a', if_sheet_exists = 'overlay') as writer:
            # 獲取現有的工作表
            start_row = writer.book['Tweets'].max_row

            # 從最後一行之後開始寫入 Excel
            df.to_excel(writer, startrow = start_row, index = False, header = False, sheet_name = 'Tweets')
    else:
        with pd.ExcelWriter(tweet_excel_path, engine = 'openpyxl') as writer:
            df.to_excel(writer, index = False, sheet_name = 'Tweets')


    print(f"\033[92m推文資料已成功寫入 {tweet_excel_path}\033[0m")
    print('-'*150)


class TwitterMediaDownloader:
    def __init__(self, tweet_media_folder, tweet_video_downloader):
        self.tweet_media_folder = tweet_media_folder
        self.tweet_video_downloader = tweet_video_downloader

    def download(self, tweet_content):
        media_type  = tweet_content['media_type']
        self.username    = tweet_content['username']
        self.status      = tweet_content['status']
        self.media_links = tweet_content['media_links']
        self.tweet_time  = tweet_content['tweet_time']

        # 轉換時間 2024-10-03T09:39:17.000Z -> 2410030939
        dt = datetime.strptime(self.tweet_time, "%Y-%m-%dT%H:%M:%S.%fZ")
        self.tweet_time = dt.strftime("%y%m%d%H%M")


        download_methods = {
            'image': self._download_image,
            'video': self._download_video,
            'gif': self._download_gif
        }

        if media_type in download_methods:
            download_methods[media_type]()
        else:
            print(f"未定義的媒體類型：{media_type}")

    def _download_image(self):
        for idx, image_url in enumerate(self.media_links):
            filename = f"twi@{self.username}_{self.tweet_time}_{self.status}_{idx + 1}.jpg"
            self._download_file(image_url, filename)

    def _download_video(self):
        url = f"https://x.com/{self.username}/status/{self.status}"
        self.tweet_video_downloader.download(url, m3u8_urls = self.media_links, folder = self.tweet_media_folder)

    def _download_gif(self):
        for idx, gif_url in enumerate(self.media_links):
            filename = f"twi@{self.username}_{self.tweet_time}_{self.status}_{idx + 1}.mp4"
            self._download_file(gif_url, filename)

    def _download_file(self, url, filename):
        urllib.request.urlretrieve(url, self.tweet_media_folder / filename)




if __name__=='__main__':
   
    # 設定目標URL和認證資訊
    target_url = "https://x.com/xxx/media"

    # 從URL提取用戶名
    username = target_url.split('/')[-2]

    
    # 設定輸出路徑
    root_folder = "../twitter post downloader/"
    tweet_media_folder = Path(root_folder) / Path(f"twi@{username}")
    tweet_excel_path = tweet_media_folder / f'twi@{username}_tweets.xlsx'
    
    # 確保輸出資料夾存在
    tweet_media_folder.mkdir(exist_ok = True)
    
    # 初始化瀏覽器
    driver = create_driver()
    cookie_file = "../twitter_auth_cookies.json"
    cookie_login(driver, cookie_file)
    
    # 初始化提取器和下載器
    media_extractor  = TwitterMediaLinkExtractor(driver)
    video_downloader = TwitterVideoDownloader(driver)
    media_downloader = TwitterMediaDownloader(tweet_media_folder, video_downloader)
    
    # 提取推文內容
    tweet_content_list = media_extractor.get_media_content(target_url, tweet_amount = 99999, tweet_excel_path = tweet_excel_path)
    
    # 下載媒體
    for index, tweet_content in enumerate(tweet_content_list, 1):
        print(f"{index:3d} / {len(tweet_content_list):3d} : {tweet_content['url']}")
        media_downloader.download(tweet_content)
    
    driver.quit()

        
