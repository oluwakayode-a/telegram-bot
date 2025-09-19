import html
import json
from lib2to3.pgen2 import driver
from unicodedata import category
from django.db import IntegrityError
from seleniumwire import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.proxy import Proxy, ProxyType
from dateutil.relativedelta import relativedelta
from dateutil.parser import parse
import datetime
from jobs.models import Job, Category
from utils.tools import get_proxy
from django.conf import settings
import re
import openai
from accounts.models import User
from resume.models import CV
from django.template.loader import render_to_string
from django.core.mail import send_mail
import feedparser

################# JOBS DATA FROM JOBBERMAN

SUPPORTED_LOCATIONS = ["Abeokuta & Ogun State", "Abuja", "Enugu", "Ibadan & Oyo State", "Imo", "Lagos",
                                "Port Harcourt & Rivers State", "Rest of Nigeria", "Outside Nigeria", "Remote (Work From Home)"                               
                               ]

SUPPORTED_JOB_TYPES = ["Contract", "Full Time", "Internship & Graduate", "Part Time"]

SUPPORTED_INDUSTRIES = ["Advertising, Media & Communications", "Agriculture, Fishing & Forestry", "Automotive & Aviation",
                        "Banking, Finance & Insurance", "Construction", "Education", "Energy & Utilities", "Enforcement & Security",
                        "Entertainment, Events & Sport", "Healthcare", "Hospitality & Hotel", "IT & Telecoms", "Law & Compliance",
                        "Manufacturing & Warehousing", "Mining, Energy & Meals", "NGO, NPO & Charity", "Real Estate", "Recruitment",
                        "Retail, Fashion & FMCG", "Shipping & Logistics", "Tourism & Travel"
                        ]


def parse_date(date_string: str):
    
    date_string = date_string.lower()

    try:
        if "today" in date_string:
            date = datetime.datetime.now()
        elif "days ago" in date_string:
            # If the string contains "day", extract the number of days and subtract from today's date
            days_ago = int(date_string.split()[0])
            date = datetime.datetime.now() - relativedelta(days=days_ago)
        elif "yesterday" in date_string:
            # If the string is "yesterday", subtract one day from today's date
            date = datetime.datetime.now() - datetime.timedelta(days=1)
        elif "week" in date_string:
            # If the string contains "week", extract the number of weeks and subtract from today's date
            weeks_ago = int(date_string.split()[0])
            date = datetime.datetime.now() - relativedelta(weeks=weeks_ago)
        elif "month" in date_string:
            months_ago = int(date_string.split()[0])
            date = datetime.datetime.now() - relativedelta(months=months_ago)
        else:
            print("cannot be parsed", date_string)

            # If the string cannot be parsed, set the date to None
            date = None
    except Exception as e:
        print(e)
        date = None
    
    # Print the parsed date
    return parse(str(date)).strftime("%Y-%m-%d %H:%M:%S") if date is not None else date_string


def create_driver():
    # Set up the Chrome driver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    # options.add_argument("--disable-gpu")
    options.add_argument('--no-sandbox')
    # options.add_argument('--disable-dev-shm-usage')

    capabilities = {
        "browserName": "chrome",
        'browserless:token' : settings.BROWSERLESS_API_KEY
    }
    capabilities.update(options.to_capabilities())

    proxy_server_url = get_proxy()

    print("working", proxy_server_url)

    # options.add_argument(f'--proxy-server={proxy_server_url}')

    wire_options = {
        'auto_config': False,
        'addr': '0.0.0.0',
        'proxy': {
            'http': f'http://kdnithzs:3nhvct5ohugb@{proxy_server_url}', 
            'https': f'https://kdnithzs:3nhvct5ohugb@{proxy_server_url}',
            'no_proxy': 'localhost,127.0.0.1' # excludes
        }
    }

    driver = webdriver.Remote(
        command_executor='https://chrome.browserless.io/webdriver',
        desired_capabilities=capabilities, seleniumwire_options=wire_options
    )
    return driver

def add_job(job):
    category, created = Category.objects.get_or_create(name=job["category"])
    
    try:
        job = Job.objects.create(
            title=job["title"],
            company_name=job["company_name"],
            category=category,
            minimum_qualification=job["minimum_qualification"],
            url=job["url"],
            experience_level=job["experience_level"],
            experience_length=job["experience_length"],
            remuneration=job["remuneration"],
            job_summary=job['job_summary'],
            date_posted = job["date_posted"],
            job_responsibilities = job["job_responsibilities"],
            requirements=job["requirements"],
            location=job["location"],
            industry=job["industry"],
            job_type=job["job_type"]
        )
    except IntegrityError as e:
        print(e)
        return Job.objects.get(url=job["url"]), "already added"

    job.save()

    return job, "created"

def scrape_jobs():
    
    driver = create_driver()

    driver.get('http://httpbin.org/ip')

    # driver.close()

    jobs = []

    job_links = []

    driver.get("https://www.jobberman.com/jobs")
    break_outer_loop = False

    while True:
        job_elements = driver.find_elements(By.XPATH, '//*[@data-cy="listing-cards-components"]')

        for job_element in job_elements[3:]:
            link = job_element.find_element(By.XPATH, './/a[@title]').get_attribute("href")

            
            
            #if link already exists in the database, break the loop
            if Job.objects.filter(url=link).exists():
                break_outer_loop = True
                break
            job_links.append(link)
            print("Job Scraped", link)
        
        if break_outer_loop:
            break
        

        # Run pagination.
        try:
            next_button = driver.find_element(By.XPATH, '//*[@aria-label="Next »"]')

            driver.execute_script("arguments[0].click();", next_button)
            WebDriverWait(driver, 10).until(EC.staleness_of(job_elements[0]))

            print("disabled", next_button.get_attribute("aria-disabled"))

            if "true" in next_button.get_attribute("aria-disabled"):
                break
        except NoSuchElementException:
            continue
        except StaleElementReferenceException:
            continue
        except TimeoutException:
            break

        

    for link in job_links:
        driver.get(link)


        job_detail = driver.find_element(By.CSS_SELECTOR, '.job__details')
        
        # Not all jobs have remuneration.
        try:
            remuneration = job_detail.find_element(By.XPATH, ".//*[contains(text(), 'NGN')]/parent::*/span").text
            
        except NoSuchElementException as e:
            print(e)
            remuneration = ""
        

        try:
            date = job_detail.find_element(By.XPATH, "//div[contains(text(), 'terday') or contains(text(), 'days ago') or contains(text(), 'oday') or contains(text(), 'week ago') or contains(text(), 'weeks ago') or contains(text(), 'months ago') or contains(text(), 'month ago')]").get_attribute('innerText')
            # date = job_detail.find_element_by_xpath("//div[contains(text(), 'Today')]").get_attribute('innerText')
        except NoSuchElementException as e:
            print(e)
            date = ""


        try:
            desc_resps = job_detail.find_elements(By.CSS_SELECTOR, '.list-disc')
            resp_list = desc_resps[1].find_elements(By.CSS_SELECTOR, 'li')
            req_list = desc_resps[2].find_elements(By.CSS_SELECTOR, 'li')
            job_responsibilities = [li.get_attribute('innerText') for li in resp_list]
            job_requirements = [li.get_attribute('innerText') for li in req_list]
        except:
            job_responsibilities = []
            job_requirements = []
        
        location = ""
        job_type = ""
        industry = ""
        

        for l in SUPPORTED_LOCATIONS:
            try:
                _location = job_detail.find_element(By.XPATH, f".//a[contains(text(), '{l[:5]}')]").get_attribute('innerText')
                location = _location

                print("location found", location)
                break
            except NoSuchElementException:
                print("error location", location)
                continue

        for j in SUPPORTED_JOB_TYPES:
            try:
                _job_type = job_detail.find_element(By.XPATH, f".//a[contains(text(), '{j[:5]}')]").get_attribute('innerText')
                job_type = _job_type

                print("job_type found", job_type)
                break
            except NoSuchElementException:
                print("error job_type", job_type)
                continue
        
        for i in SUPPORTED_INDUSTRIES:
            try:
                _industry = job_detail.find_element(By.XPATH, f".//a[contains(text(), '{i[:5]}')]").get_attribute('innerText')
                industry = _industry

                print("industry found", industry)
                break
            except NoSuchElementException:
                print("error industry", industry)
                continue

        job = {
            "title": job_detail.find_element(By.XPATH, './/h1').text,
            "company_name" : job_detail.find_element(By.XPATH, './/h2[1]').text,
            "category" : job_detail.find_element(By.XPATH, './/h2[2]').text,
            "minimum_qualification" : job_detail.find_element(By.XPATH, ".//span[contains(text(), 'Minimum Qual')]/following-sibling::span").get_attribute('innerText'),
            "url": link,
            "experience_level" : job_detail.find_element(By.XPATH, ".//span[contains(text(), 'Experience Lev')]/following-sibling::span").get_attribute('innerText'),
            "experience_length" : job_detail.find_element(By.XPATH, ".//span[contains(text(), 'Experience Leng')]/following-sibling::span").get_attribute('innerText'),
            "remuneration" : remuneration,
            "job_summary" : job_detail.find_element(By.XPATH, ".//h3[contains(text(), 'Job Sum')]/following-sibling::p").get_attribute('innerText'),
            "date_posted": parse_date(date),
            "job_responsibilities" : job_responsibilities,
            "requirements" : job_requirements,
            "location" : location,
            "job_type" : job_type,
            "industry" : industry
        }

        # Check if job category already exists.
        
        job_obj, status = add_job(job)

        print(f"Job {status}", job_obj.id, job_obj.title)
    driver.close()
    print("\n\n\nOperation Completed.")


# def fetch_jobs_from_job_gurus():
#     job_parser = feedparser.parse("https://jobgurus.com.ng/jobs/feed")

#     jobs = job_parser["entries"]

#     title
#     link
#     summary
#     published
#     location
#     company
#     workLevel

#     job = {
#             "title": 
#             "company_name" : 
#             "category" : 
#             "minimum_qualification" : ,
#             "url": link,
#             "experience_level" : ,
#             "experience_length" : ,
#             "remuneration" : ,
#             "job_summary" : ,
#             "date_posted": ,
#             "job_responsibilities" : ,
#             "requirements" : 
#     }

    



def get_category_from_job_title(job_title):
    categories = Category.objects.all()
    #convert cateories to string seperated by commas
    categories = ",".join([category.name for category in categories])
    #remove all non-alphanumeric characters
    #categories = re.sub(r'[^a-zA-Z0-9,]', '', categories)
    prompt = "Given job title '%s' and job categories '%s'. Return a single category that the job title falls under. Be as precise as possible. If it does not match any of the categories return null" %(job_title, categories)
    #print(prompt)
    try:
        completion = openai.Completion.create(
            model="gpt-3.5-turbo-instruct", 
            prompt=prompt, 
            temperature=0.9, 
            max_tokens=100,
            )
        
        category = completion['choices'][0]['text']
    #remove \n from the string
        category = category.replace('\n', '')
        if category == 'null':
            return ''
        else:
            return category

    except Exception as e:
        print(e)
        pass


def set_user_job_category():
    users = User.objects.all()
    for user in users:
        if user.job_category:
            user.job_category = user.job_category.replace('.', '')
            user.save()
            continue
        #get latest cv created by user  
        cvs = CV.objects.filter(user=user).order_by('-created_at')
        jobTitle = None
        if user.job_title:
            jobTitle = user.job_title
        else:
            for cv in cvs:
                try:
                    jobTitle = cv.cv_object['personalInfo']['jobTitle']
                    break
                except KeyError:
                    continue       
        if jobTitle:
            job_category = get_category_from_job_title(jobTitle)  
            print(job_category)       
            if job_category:
                user.job_category = job_category
                user.save()

def get_latest_user_jobs(user):
    job_category = user.job_category
    if job_category:
        jobs = Job.objects.filter(category__name__icontains=job_category).order_by('-date_posted')[:5]
        return jobs
    else:
        return None


def send_job_alert_to_user(user, latest_job):
    jobs = get_latest_user_jobs(user)
    if not jobs:
        jobs = latest_job
    if jobs:
        html_message = render_to_string('emails/job_alert.html', {'jobs': jobs, 'user': user, 'category': user.job_category})
        plain_message = "job alert"
        from_email = 'FinezCV Jobs<jobs@finezcv.com>'
        to = user.email
        subject = 'New Curated Jobs for you'
        try:
            send_mail(subject, plain_message, from_email, [to], html_message=html_message)
        except Exception as e:
            print(e)
            pass

    else:
        return None
        


def send_job_alerts():
    users = User.objects.filter(location='nigeria')
    latest_jobs = Job.objects.all().order_by('-date_posted')[:5]
    for user in users:
        if user.jobs_alert_approved:
            send_job_alert_to_user(user, latest_jobs)


    

