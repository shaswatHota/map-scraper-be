from playwright.sync_api import sync_playwright, TimeoutError
from bs4 import BeautifulSoup
import csv
import re

def extract_cafe_data(page):
    """
    Extracts cafe information from the details page using robust selectors.
    """
    data = {
        'name': 'Not found',
        'rating': 'Not found',
        'reviews_count': 'Not found',
        'address': 'Not found',
        'phone': 'Not found',
        'website': 'Not found',
        'opening_hours': 'Not found',
        'price_range': 'Not found'
    }

    try:
        # 1. Extract Name - More stable by targeting the main H1
        try:
            name_element = page.locator('h1').first
            name_element.wait_for(state="visible", timeout=2000)
            data['name'] = name_element.inner_text().strip()
        except TimeoutError:
            print("Warning: Cafe name (h1) not found.")

        # 2. Extract Rating & Reviews - Uses aria-label for stability
        try:
            # The aria-label is descriptive and less likely to change than classes.
            rating_element = page.locator('span[aria-label*="stars"]').first
            rating_text = rating_element.inner_text().strip()
            # Split text like "4.6 6,006 reviews"
            parts = rating_text.split()
            if parts:
                data['rating'] = parts[0]
                if len(parts) > 1:
                   data['reviews_count'] = parts[1].replace(',', '')
        except TimeoutError:
            print(f"Warning: Rating not found for {data['name']}.")

        # 3. Extract Address - `data-item-id` is a more reliable hook than CSS classes
        try:
            address_element = page.locator('button[data-item-id="address"]').first
            data['address'] = address_element.get_attribute('aria-label').replace('Address:', '').strip()
        except TimeoutError:
            print(f"Warning: Address not found for {data['name']}.")

        # 4. Extract Phone Number - `data-item-id` starting with 'phone:tel:' is very specific
        try:
            phone_element = page.locator('button[data-item-id^="phone:tel:"]').first
            data['phone'] = phone_element.get_attribute('aria-label').replace('Phone:', '').strip()
        except TimeoutError:
            print(f"Warning: Phone number not found for {data['name']}.")
            
        # 5. Extract Website - `data-item-id="authority"` is often used for the official link
        try:
            website_element = page.locator('a[data-item-id="authority"]').first
            data['website'] = website_element.get_attribute('href')
        except TimeoutError:
             print(f"Warning: Website not found for {data['name']}.")

        # 6. Extract Opening Hours - Finds by aria-label containing "Hours"
        try:
            hours_element = page.locator('[aria-label*="Hours"]').first
            data['opening_hours'] = hours_element.get_attribute('aria-label')
        except TimeoutError:
             print(f"Warning: Opening hours not found for {data['name']}.")

        # 7. Extract Price Range - Finds by looking for a currency symbol
        try:
            # This looks for a div containing the currency symbol, which is more robust than a class.
            price_element = page.locator("div:text-matches('[₹$€]')").first
            data['price_range'] = price_element.inner_text().strip()
        except TimeoutError:
            print(f"Warning: Price range not found for {data['name']}.")

    except Exception as e:
        print(f"An unexpected error occurred while extracting data: {e}")

    return data


def scrape_cafes(search_term="cafe near bhubaneswar", max_results=10):
    """Main scraping function"""
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=False, slow_mo=50)
        page = browser.new_page()

        try:
            print("Opening Google Maps...")
            page.goto('https://www.google.com/maps', timeout=60000)

            print(f"Searching for: {search_term}")
            page.locator('input#searchboxinput').fill(search_term)
            page.locator('button[aria-label="Search"]').click()

            # Wait for the main feed of results to appear
            print("Waiting for search results...")
            page.wait_for_selector('div[role="feed"]', timeout=10000)
            page.wait_for_timeout(3000) # Additional wait for all items to render

            # Improved selector for listings: targets links to places, which is more stable than generated classes.
            listings = page.locator('div[role="feed"] a[href*="/maps/place/"]').all()
            print(f"Found {len(listings)} cafe listings.")

            results = []
            if not listings:
                print("No listings found. The page structure may have changed.")
                return []

            for i in range(min(max_results, len(listings))):
                listing = listings[i]
                print(f"\nScraping cafe #{i+1}...")

                try:
                    listing.click()
                    # Wait for the main heading (h1) of the details page to be visible
                    page.wait_for_selector("h1", state="visible", timeout=10000)
                    page.wait_for_timeout(2000) # Allow time for all details to load

                    cafe_data = extract_cafe_data(page)
                    cafe_data['search_rank'] = i + 1
                    
                    # Check if at least a name was scraped
                    if cafe_data['name'] != 'Not found':
                        print(f"✓ Successfully scraped: {cafe_data['name']}")
                        results.append(cafe_data)
                    else:
                        print("✗ Failed to scrape essential data for cafe #{i+1}.")

                except Exception as e:
                    print(f"✗ Failed to click or process listing #{i+1}: {e}")
                    # In case of an error, try to go back to the search to continue
                    page.goto(f'https://www.google.com/maps/search/{search_term.replace(" ", "+")}')
                    page.wait_for_timeout(5000)
                    listings = page.locator('div[role="feed"] a[href*="/maps/place/"]').all() # Re-fetch listings
                    continue

        except TimeoutError:
            print("Error: Timed out waiting for a page element. The website may be slow or has changed.")
        except Exception as e:
            print(f"A critical error occurred: {e}")
        finally:
            print("\nClosing browser.")
            browser.close()

        return results


def save_to_csv(data, filename='cafes_bhubaneswar.csv'):
    """Save scraped data to a CSV file"""
    if not data:
        print("No data was scraped to save.")
        return

    print(f"\nSaving {len(data)} cafes to {filename}...")
    fieldnames = [
        'search_rank', 'name', 'rating', 'reviews_count', 'address', 
        'phone', 'website', 'opening_hours', 'price_range'
    ]

    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)

    print(f"✓ Data successfully saved to {filename}")


if __name__ == "__main__":
    # --- Configuration ---
    SEARCH_TERM = "cafe near Bhubaneswar"
    MAX_RESULTS = 15  # Increased for a more comprehensive list
    OUTPUT_FILE = "cafes_bhubaneswar_improved.csv"
    # ---------------------
    
    print("=" * 35)
    print("=== Google Maps Cafe Scraper (Improved) ===")
    print(f"Search Term: {SEARCH_TERM}")
    print(f"Max Results: {MAX_RESULTS}")
    print(f"Output File: {OUTPUT_FILE}")
    print("=" * 35)

    scraped_data = scrape_cafes(SEARCH_TERM, MAX_RESULTS)
    save_to_csv(scraped_data, OUTPUT_FILE)

    print("\n=== Scraping Complete ===")