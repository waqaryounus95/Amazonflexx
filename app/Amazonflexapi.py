import json
import logging
from appium import webdriver
from appium.options.android import UiAutomator2Options
from time import sleep
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
import subprocess
import requests
import os
from dotenv import load_dotenv
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from twilio.rest import Client
from models import User, OfferLog, db ,UserPreference
from datetime import datetime, timedelta
from flask import session ,request
import time

# Configure logging
logging.basicConfig(filename='offers_log.csv', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

load_dotenv()

SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL')

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')
TO_PHONE_NUMBER = os.getenv('TO_PHONE_NUMBER')

class UserScript:
    def __init__(self, device_config, user_email, user_password, user_id):
        self.device_config = device_config
        self.user_email = user_email
        self.user_password = user_password
        self.user_id = user_id
        self.running = False
        self.last_search_time = None
        self.driver = None


    def start(self):
        self.running = True
        self.last_search_time = datetime.now()
        self.driver = initialize_driver(
            self.device_config['device_name'],
            self.device_config['udid'],
            self.device_config['platform_version'],
            self.device_config['appium_server_url']
        )
        try:
            if not initial_setup(self.driver, self.user_email, self.user_password):
                self.running = False
                return
        except Exception as e:
            logging.error(f"Initial setup failed for user {self.user_id}: {e}")
            self.running = False
            return
        process_offers(self.driver, self.user_id, self)

    def stop(self):
        self.running = False
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logging.error(f"Error quitting driver for user {self.user_id}: {e}")

def send_email(subject, body , to_email):
    """Send an email notification."""
    msg = MIMEMultipart()
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(EMAIL_ADDRESS, NOTIFICATION_EMAIL, text)
        server.quit()
        logging.info(f"Email sent: {subject}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

def send_sms(message , to_phone):
    """Send an SMS notification."""
    try:
        if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
            logging.warning("Twilio credentials not configured. SMS notification skipped.")
            return
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        client.messages.create(
            from_=TWILIO_PHONE_NUMBER,
            body=message,
            to=to_phone
        )
        logging.info(f"SMS sent to {to_phone}: {message}")
    except Exception as e:
        logging.error(f"Failed to send SMS: {e}")

def notify_offer_status(offer_data, status , user_email , user_phone):
    """Notify the user of an offer status change."""
    message = f"Offer {status}: {offer_data['header']} - {offer_data['details']}"
    if user_phone:
        send_sms(message , user_phone)    
    send_email(f"Offer {status}", message , user_email)

def handle_permissions(driver , user_state):
    """Handle location and general permissions if they are requested by the app."""
    try:
        while user_state.running:
            location_permission = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, "//android.widget.Button[@text='While using the app']"))
            )
            location_permission.click()
            logging.info("Granted location permission.")
    except TimeoutException:
        logging.info("Location permissions handled or not found.")

    try:
         while user_state.running:
            allow_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, "//android.widget.Button[@text='Allow']"))
            )
            allow_button.click()
            logging.info("Granted general permission.")
    except TimeoutException:
        logging.info("General permissions handled or not found.")

def load_accepted_offers():
    """Load the accepted offers from a JSON file."""
    try:
        with open("offers_data.json", "r") as file:
            offers_data = json.load(file)
            return offers_data
    except FileNotFoundError:
        return []

def initial_setup(driver, user_email, user_password):
    """Perform initial setup tasks such as signing in, handling permissions, and opening the offers menu."""
    try:
        sign_in_button = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((AppiumBy.ID, "com.amazon.flex.rabbit:id/sign_in_button"))
        )
        logging.info("Sign-in required, proceeding with login.")
        
        sign_in_button.click()
        email_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.EditText[@text="Username or email address"]'))
        )
        email_field.send_keys(user_email)

        password_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.EditText[@text="Password"]'))
        )
        password_field.send_keys(user_password)

        sign_in_button_after_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/go_to_sign_in_button"))
        )
        sign_in_button_after_input.click()

        logging.info("Signed in successfully.")

    except TimeoutException:
        logging.info("User is already logged in. Proceeding without login.") 

    try:
        contact_stop = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/primaryButton"))
        )
        contact_stop.click()
        logging.info("Contact stop clicked!")
    except TimeoutException:
        logging.info("Contact stop button not found.")

    try:
        notification_close = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/toolbar_close_button"))
        )
        notification_close.click()
        logging.info("Notification closed!")
    except TimeoutException:
        logging.info("Notification close button not found.")

    try:
        nav_bar = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.ImageButton[@content-desc="Navigate up"]'))
        )
        nav_bar.click()
        logging.info("Navigation bar clicked.")
    except TimeoutException:
        logging.info("Navigation bar button not found.")

    try:
        menu_offers = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/menu_offers"))
        )
        menu_offers.click()
        logging.info("Opened offers menu.")
        return True  
    except TimeoutException:
        logging.info("menu_offers button not found.")
        return True

def get_weekday_from_string(date_str: str) -> str:
    """
    Helper function to get the weekday name from a date string.Expected format: "Monday, 03/13". If the input is not in that format,
    it falls back to using the current weekday.
    """
    try:
        if ',' not in date_str:
            raise ValueError("Date string not in expected format")
        current_year = datetime.now().year
        date_str_with_year = f"{date_str}/{current_year}"
        date_obj = datetime.strptime(date_str_with_year, "%A, %m/%d/%Y")
        return date_obj.strftime("%A")
    except Exception as e:
        print(f"Error parsing date: {e}. Falling back to current weekday.")
        return datetime.now().strftime("%A")

# search_interval = 30  # seconds
def process_offers(driver, user_id , user_state):
    """
    Process Amazon Flex offers by extracting details, comparing them with user filters,auto-accepting matching offers (by creating a new DB record and then calling the API),
    and checking for forfeit action.If an error occurs while processing an offer, it navigates back and skips that offer.
    """
    accepted_offers = load_accepted_offers()
    from app import app
    
    with app.app_context():
        user = User.query.get(user_id)
        user_email = user.email if user else None        
        user_phone = user.contact_no if user else None        
        user_preference = UserPreference.query.filter_by(user_id=user_id).first()

    if user_preference:
        pref_days = set(entry['day'] for entry in user_preference.weekly_availability)
        pref_stations = {station['name']: station for station in user_preference.stations}
    else:
        from app import valid_days , get_valid_stations
        pref_days = set(valid_days)
        valid_stations = get_valid_stations()
        pref_stations = {name: {"offer_min_price": 0, "hourly_min_price": 0, "eta": 0} for name in valid_stations}
   
    def check_user_preference(offer_data, pref_stations, pref_days):
        offer_station = offer_data.get("offer_details_station")
        offer_date = offer_data.get("offer_date")

        if not offer_station or not offer_date:
            return False
            
        if offer_station not in pref_stations:
            logging.info(f"Station {offer_station} not in preferred stations")
            return False
            
        offer_day = get_weekday_from_string(offer_date)
        if offer_day not in pref_days:
            logging.info(f"Day {offer_day} not in preferred days")
            return False
            
        station_filter = pref_stations[offer_station]
        min_price = station_filter.get("offer_min_price", None)
        
        if min_price is None:
            logging.info(f"No minimum price set for station {offer_station}")
            return False
            
        try:
            offer_amount_str = offer_data.get("pay_range_with_tips", "")
            if not offer_amount_str:
                logging.info("No pay range found in offer")
                return False
                
            offer_amount = float(offer_amount_str.replace("$", "").replace(",", ""))
            
            if offer_amount < min_price:
                logging.info(f"Offer amount ${offer_amount} below minimum ${min_price}")
                return False
                
            logging.info(f"Offer matches all criteria: station={offer_station}, day={offer_day}, amount=${offer_amount}>=${min_price}")
            return True
            
        except Exception as e:
            logging.error(f"Error parsing offer amount '{offer_amount_str}': {e}")
            return False
        
    while user_state.running:
        try:
            filter_element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/filter_offer_count'))
            )
            filter_text = filter_element.text
            total_offers = int(filter_text.split(' ')[2])
            logging.info(f"Total offers: {total_offers}")
        except Exception as e:
            logging.error(f"Error fetching total offers: {e}")
            break
        try:
            offer_elements = WebDriverWait(driver, 10).until(
                EC.presence_of_all_elements_located((AppiumBy.XPATH,
                    '//androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout'))
            )
        except Exception as e:
            logging.error(f"Error fetching offer elements: {e}")
            continue

        for idx in range(1, total_offers + 1):
            if not user_state.running:
                return

            try:
                current_offers = driver.find_elements(AppiumBy.XPATH,'//androidx.recyclerview.widget.RecyclerView/android.widget.LinearLayout')
                if idx > len(current_offers):
                    continue

                current_offer = current_offers[idx - 1]
                current_offer.click()
                logging.info(f"Clicked on offer {idx}")
            except Exception as e:
                logging.error(f"Error clicking on offer {idx}: {e}")
                try:
                    driver.back()
                    logging.info("Navigated back after clicking issue.")
                except Exception as back_err:
                    logging.error(f"Error navigating back after click failure: {back_err}")
                continue

            offer_details_station = ""
            offer_details_station_address = ""
            offer_date = ""
            offer_time_window = ""
            pay_range_with_tips = ""
            pay_description = ""

            try:
                offer_details_station = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/offer_details_station'))
                ).text
                offer_details_station_address = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/offer_details_station_address'))
                ).text
                header_text = f"{offer_details_station} {offer_details_station_address}"

                offer_date = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/offer_date'))
                ).text
                offer_time_window = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/offer_time_window'))
                ).text
                pay_range_with_tips = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/pay_range_with_tips'))
                ).text
                pay_description = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((AppiumBy.ID, 'com.amazon.flex.rabbit:id/pay_description'))
                ).text
            except Exception as e:
                logging.error(f"Error extracting details for offer {idx}: {e}")                
                continue

            details_text = f"{offer_date} {offer_time_window} {pay_range_with_tips} {pay_description}"
            offer_data = {
                "offer_details_station": offer_details_station,
                "offer_details_station_address": offer_details_station_address,
                "offer_date": offer_date,
                "offer_time_window": offer_time_window,
                "pay_range_with_tips": pay_range_with_tips,
                "pay_description": pay_description
            }
            offer_dataa = {"header": header_text, "details": details_text}

            logging.info(f"Processing offer {idx}: {header_text} - {details_text}")

            if any(
                isinstance(o, dict) and "offer_dataa" in o and
                o["offer_dataa"].get("header") == header_text and
                o["offer_dataa"].get("details") == details_text
                for o in accepted_offers
            ):
                logging.info(f"Offer {idx} already accepted: {header_text}")
                try:
                    driver.back()
                except Exception:
                    pass
                continue

            if check_user_preference(offer_data, pref_stations, pref_days):
                logging.info(f"Auto-accepting offer {idx} as it matches filters.")
                try:
                    schedule_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/primaryButton"))
                    )
                    schedule_button.click()
                    logging.info(f"Clicked schedule button for offer {idx}")
                    try:
                        order_popup = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located(
                                (AppiumBy.ID, "com.amazon.flex.rabbit:id/meridian_alert_title_large_thumbnail")
                            )
                        ).text
                        if order_popup.strip() == "Offer scheduled":
                            logging.info(f"Offer {idx} scheduled successfully.")
                        
                            from models import OfferLog
                            from app import app
                            with app.app_context():
                                new_offer = OfferLog(
                                    user_id=user_id,
                                    offer_details_station=offer_details_station,
                                    offer_details_station_address=offer_details_station_address,
                                    offer_date=offer_date,
                                    offer_time_window=offer_time_window,
                                    pay_range_with_tips=pay_range_with_tips,
                                    pay_description=pay_description,
                                    status='accepted'
                                )
                                db.session.add(new_offer)
                                db.session.commit()
                                db_offer_id = new_offer.id
                            logging.info(f"New offer record created with ID: {db_offer_id}")
                            headers = {'Content-Type': 'application/json'}
                            response = requests.post('http://localhost:5000/accept_offer',
                                                     json={
                                                         "user_id": user_id,
                                                         "offer_id": db_offer_id,
                                                         "offer_details": header_text,
                                                         "offer_amount": pay_range_with_tips
                                                     },
                                                     headers=headers)                            
                            
                            if response.status_code == 200:
                                logging.info(f"Offer {idx} accepted and logged. (DB ID: {db_offer_id})")
                                notify_offer_status(offer_dataa, "accepted" , user_email , user_phone)
                            else:
                                logging.error(f"Failed to log accepted offer {idx}. Response status: {response.status_code}")
                        else:
                            raise TimeoutException("Offer scheduled popup did not match expected text.")
                    except TimeoutException as te:
                        logging.info(f"Order scheduled popup not detected for offer {idx}; offer missed.")
                except Exception as e:
                    logging.error(f"Error clicking schedule button for offer {idx}: {e}")
            else:
                logging.info(f"Offer {idx} does not match filters")
                driver.back()                
            try:
                continue
                logging.info(f"Returned to offer list after processing offer {idx}")
            except Exception as nav_err:
                logging.error(f"Error navigating back after offer {idx}: {nav_err}")
                continue

        try:
            refresh_button = WebDriverWait(driver, 30).until(
                EC.element_to_be_clickable((AppiumBy.ID, 'com.amazon.flex.rabbit:id/primaryButton'))
            )
            refresh_button.click()
            logging.info("Clicked refresh button to load new offers.")
        except Exception as e:
            logging.error(f"Error refreshing offers: {e}")
            break

def forfeit_offer(driver, day_of_month):
    """Forfeit a specific block by tapping the day_of_month in the Amazon Flex schedule UI and confirming the forfeit."""
    try:
        nav_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.ImageButton[@content-desc="Navigate up"]'))
        )
        nav_button.click()
        logging.info("Tapped the 'Navigate up' button in the side menu.")

        schedule_menu = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/menu_schedule"))
        )
        schedule_menu.click()
        logging.info("Opened the schedule screen.")

        day_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.XPATH, f'//android.widget.TextView[@text="{day_of_month}"]'))
        )
        day_button.click()
        logging.info(f"Selected day {day_of_month} in the schedule calendar.")

        block_card = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/card"))
        )
        block_card.click()
        logging.info("Tapped the block card to open details.")

        forfeit_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/primaryButton"))
        )
        forfeit_btn.click()
        logging.info("Tapped 'Forfeit' button.")

        click_yes = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((AppiumBy.ID, 'com.amazon.flex.rabbit:id/primaryButton'))
        )
        click_yes.click()
        logging.info("Confirmed forfeit with 'Yes'.")
        try:            
            order_popup = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (AppiumBy.ID, "com.amazon.flex.rabbit:id/meridian_alert_title_large_thumbnail")
                )
            ).text
            if order_popup.strip() == "You've forfeited the block": 
                logging.info(f"Offer forfited successfully.") 
                return True
            else:
                logging.error(f"Unexpected popup text: {order_popup}")
                return False 
        except Exception as e:
            logging.error("error in forfiet") 
            return False      

    except TimeoutException:
        logging.info("Could not find the necessary UI elements to forfeit.")
    except Exception as e:
        logging.error(f"Error while forfeiting offer: {e}")

def scrape_stations(driver):
    """
    Scrape available stations from Amazon Flex app using the correct element IDs
    Returns a list of station names with scroll handling
    """
    try:
        # Navigate to offers section if not already there
        try:
            nav_bar = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.XPATH, '//android.widget.ImageButton[@content-desc="Navigate up"]'))
            )
            nav_bar.click()
            
            menu_offers = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/menu_offers"))
            )
            menu_offers.click()
            logging.info("Navigated to offers screen")
        except Exception as e:
            logging.info(f"Already on offers screen or navigation failed: {e}")

        # Click filters button to open filter view
        try:
            filter_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((AppiumBy.ID, "com.amazon.flex.rabbit:id/filter_button_title"))
            )
            filter_button.click()
            logging.info("Clicked filter button")
            
            # Initialize stations set to avoid duplicates
            stations_set = set()
            last_stations_count = 0
            scroll_attempts = 0
            max_scroll_attempts = 10  # Maximum number of scroll attempts
            
            while scroll_attempts < max_scroll_attempts:
                # Get current visible stations
                station_elements = driver.find_elements(
                    AppiumBy.XPATH,
                    '//android.widget.TextView[@resource-id="com.amazon.flex.rabbit:id/filters_view_service_area_details"]'
                )
                
                # Add new stations to set
                current_stations = {station.text for station in station_elements if station and station.text}
                stations_set.update(current_stations)
                
                # If no new stations found after scrolling, we've reached the end
                if len(stations_set) == last_stations_count:
                    scroll_attempts += 1
                else:
                    scroll_attempts = 0  # Reset counter if new stations found
                    
                last_stations_count = len(stations_set)
                
                # Scroll down
                screen_size = driver.get_window_size()
                start_y = int(screen_size['height'] * 0.8)
                end_y = int(screen_size['height'] * 0.2)
                
                driver.swipe(
                    start_x=screen_size['width'] // 2,
                    start_y=start_y,
                    end_x=screen_size['width'] // 2,
                    end_y=end_y,
                    duration=500
                )
                
                # Small wait to let content settle
                time.sleep(0.5)
            
            # Convert set to sorted list
            stations = sorted(list(stations_set))
            
            # Close filter view
            driver.back()
            
            logging.info(f"Successfully scraped {len(stations)} stations")
            return stations
            
        except Exception as e:
            logging.error(f"Error accessing filters or extracting stations: {e}")
            return []
            
    except Exception as e:
        logging.error(f"Error in station scraping process: {e}")
        return []



driver = None 
def initialize_driver(device_name,udid, platform_version, appium_server_url):
    try:       
        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.device_name = device_name
        options.udid = udid
        options.platform_version = platform_version
        options.app_package = "com.amazon.flex.rabbit"
        options.app_activity = "com.amazon.rabbit.android.presentation.core.LaunchActivity"
        options.no_reset = True
        options.full_reset = False
        
        logging.info(f"Initializing driver for device {device_name},{udid} and launching the app.")
        driver = webdriver.Remote(appium_server_url, options=options)
        sleep(5)
        return driver

    except Exception as e:
        logging.error(f"Error initializing driver for device {device_name}: {e}")
        raise
    
