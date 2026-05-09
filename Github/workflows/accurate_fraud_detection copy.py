#!/usr/bin/env python3
"""
Accurate Mdundo Fraud Detection
Scrapes real data from Mdundo charts and artist pages
Posts accurate results to Slack
"""

import os
import re
import json
import requests
from datetime import datetime
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

class MdundoAccurateScraper:
    """Accurately scrapes Mdundo chart data"""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.base_url = "https://mdundo.com"

    def get_chart_data(self, country: str, limit: int = 50) -> List[Dict]:
        """
        Scrape actual chart data from Mdundo
        Returns: List of {rank, artist_name, artist_id, song_title, song_id, url}
        """
        try:
            url = f"{self.base_url}/best/{country}"
            print(f"  📥 Fetching {country.upper()} chart from {url}")

            response = self.session.get(url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            artists = []
            rank = 1

            # Find all song containers
            # Look for links that follow the pattern /a/{id} (artist pages)
            artist_links = soup.find_all('a', href=re.compile(r'/a/\d+'))

            for link in artist_links[:limit]:
                try:
                    href = link.get('href', '')
                    artist_name = link.get_text(strip=True)

                    # Extract artist ID from URL
                    match = re.search(r'/a/(\d+)', href)
                    if not match or not artist_name or len(artist_name) < 2:
                        continue

                    artist_id = match.group(1)
                    full_url = f"{self.base_url}{href}" if not href.startswith('http') else href

                    artists.append({
                        'rank': rank,
                        'artist_name': artist_name,
                        'artist_id': artist_id,
                        'artist_url': full_url,
                        'song_title': 'TBD',  # Will fetch from artist page
                        'song_id': 'TBD',
                        'monthly_listeners': 0,
                        'country': country.upper()
                    })

                    rank += 1

                except Exception as e:
                    print(f"    ⚠️ Error parsing artist: {e}")
                    continue

            print(f"  ✅ Found {len(artists)} artists on chart")
            return artists

        except Exception as e:
            print(f"  ❌ Error fetching chart: {e}")
            return []

    def get_artist_details(self, artist_id: str, artist_url: str) -> Dict:
        """
        Get accurate artist details from their Mdundo profile page
        Returns: {monthly_listeners, rank, songs, growth}
        """
        try:
            response = self.session.get(artist_url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract monthly listeners
            # Look for text like "114 140 monthly listeners"
            monthly_listeners = 0
            listener_text = soup.get_text()

            # Try to find "monthly listeners" pattern
            match = re.search(r'(\d+[\s,]*\d*)\s+monthly\s+listeners', listener_text, re.IGNORECASE)
            if match:
                num_str = match.group(1).replace(' ', '').replace(',', '')
                try:
                    monthly_listeners = int(num_str)
                except:
                    monthly_listeners = 0

            # Extract rank (from the page)
            rank_match = re.search(r'Rank:\s*(\d+)', listener_text)
            rank = int(rank_match.group(1)) if rank_match else 0

            # Extract songs (top songs on artist page)
            songs = []
            song_links = soup.find_all('a', href=re.compile(r'/song/\d+'))
            for link in song_links[:5]:  # Top 5 songs
                try:
                    song_name = link.get_text(strip=True)
                    song_url = link.get('href', '')
                    match = re.search(r'/song/(\d+)', song_url)
                    if match:
                        songs.append({
                            'title': song_name,
                            'id': match.group(1),
                            'url': f"{self.base_url}{song_url}" if not song_url.startswith('http') else song_url
                        })
                except:
                    continue

            return {
                'monthly_listeners': monthly_listeners,
                'rank': rank,
                'songs': songs,
                'verified': monthly_listeners > 0  # If we found listeners, data is verified
            }

        except Exception as e:
            print(f"    ⚠️ Error fetching artist details: {e}")
            return {
                'monthly_listeners': 0,
                'rank': 0,
                'songs': [],
                'verified': False
            }


class SpotifyChecker:
    """Checks artist presence on Spotify"""

    def __init__(self):
        try:
            client_id = os.getenv('SPOTIFY_CLIENT_ID')
            client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

            if client_id and client_secret:
                creds = SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.sp = spotipy.Spotify(client_credentials_manager=creds)
                self.available = True
            else:
                self.available = False
                print("⚠️ Spotify credentials not set")
        except Exception as e:
            self.available = False
            print(f"⚠️ Spotify not available: {e}")

    def check_artist(self, artist_name: str) -> Dict:
        """Check if artist exists on Spotify"""
        if not self.available:
            return {
                'found': False,
                'followers': 0,
                'url': '',
                'error': 'Spotify not configured'
            }

        try:
            results = self.sp.search(q=artist_name, type='artist', limit=1)

            if results['artists']['items']:
                artist = results['artists']['items'][0]
                return {
                    'found': True,
                    'name': artist['name'],
                    'followers': artist['followers']['total'],
                    'url': artist['external_urls'].get('spotify', ''),
                    'popularity': artist['popularity'],
                    'verified': artist['popularity'] > 0
                }

            return {
                'found': False,
                'followers': 0,
                'url': '',
                'error': 'Not found'
            }

        except Exception as e:
            return {
                'found': False,
                'followers': 0,
                'url': '',
                'error': str(e)
            }


class FraudDetector:
    """Detects fraud based on accurate data"""

    def __init__(self, spotify_checker: Optional[SpotifyChecker] = None):
        self.spotify = spotify_checker
        self.min_followers_for_rank = {
            5: 10000,      # Top 5 should have at least 10K followers
            10: 5000,      # Top 10 should have at least 5K
            20: 2000,      # Top 20 should have at least 2K
            50: 500,       # Top 50 should have at least 500
        }

    def analyze_artist(self, artist_data: Dict) -> Dict:
        """Analyze artist for fraud indicators"""
        fraud_score = 0
        flags = []

        rank = artist_data.get('rank', 999)
        monthly_listeners = artist_data.get('monthly_listeners', 0)
        artist_name = artist_data.get('artist_name', '')

        # Check 1: Not on Spotify
        spotify_data = {}
        if self.spotify:
            spotify_data = self.spotify.check_artist(artist_name)

        if not spotify_data.get('found'):
            fraud_score += 20
            flags.append("Not found on Spotify")
        else:
            spotify_followers = spotify_data.get('followers', 0)
            if spotify_followers < 1000:
                fraud_score += 15
                flags.append(f"Low Spotify followers ({spotify_followers:,})")

        # Check 2: Zero or very low Mdundo listeners for high rank
        if monthly_listeners == 0 and rank <= 20:
            fraud_score += 35
            flags.append(f"Top {rank} rank but 0 monthly listeners on Mdundo")
        elif monthly_listeners < 1000 and rank <= 10:
            fraud_score += 25
            flags.append(f"Top {rank} rank but only {monthly_listeners:,} monthly listeners")
        elif monthly_listeners < 5000 and rank <= 5:
            fraud_score += 30
            flags.append(f"Top 5 rank but only {monthly_listeners:,} monthly listeners")

        # Check 3: Suspicious artist names
        if any(word in artist_name.lower() for word in ['bot', 'fake', 'test', 'spam']):
            fraud_score += 25
            flags.append(f"Suspicious keyword in name: {artist_name}")

        if artist_name.isupper() and len(artist_name) > 3:
            fraud_score += 10
            flags.append("All uppercase name")

        if len(re.findall(r'\d', artist_name)) > 3:
            fraud_score += 15
            flags.append("Too many numbers in name")

        # Determine risk level
        if fraud_score >= 60:
            risk_level = "CRITICAL"
        elif fraud_score >= 40:
            risk_level = "HIGH"
        elif fraud_score >= 20:
            risk_level = "MEDIUM"
        elif fraud_score > 0:
            risk_level = "LOW"
        else:
            risk_level = "CLEAN"

        return {
            'fraud_score': min(fraud_score, 100),
            'risk_level': risk_level,
            'flags': flags,
            'spotify_data': spotify_data
        }


class SlackPoster:
    """Posts results to Slack"""

    def __init__(self, webhook_url: str):
        self.webhook = webhook_url

    def post_country_results(self, country: str, results: List[Dict]):
        """Post country fraud results to Slack"""
        if not results:
            message = f"✅ *{country}*: All clean - no suspicious artists detected"
            self._post_message(message)
            return

        flagged = [r for r in results if r['analysis']['risk_level'] != 'CLEAN']

        if not flagged:
            message = f"✅ *{country}*: {len(results)} analyzed - All clean"
            self._post_message(message)
            return

        message = f"🚨 *{country.upper()}* - Fraud Alert\n"
        message += f"Analyzed: {len(results)} | Flagged: {len(flagged)}\n"
        message += "─" * 60 + "\n\n"

        for artist in sorted(flagged, key=lambda x: x['analysis']['fraud_score'], reverse=True)[:10]:
            rank = artist['rank']
            name = artist['artist_name']
            score = artist['analysis']['fraud_score']
            risk = artist['analysis']['risk_level']
            listeners = artist['monthly_listeners']

            if risk == "CRITICAL":
                emoji = "🔴"
            elif risk == "HIGH":
                emoji = "🟠"
            else:
                emoji = "🟡"

            message += f"{emoji} *#{rank} {name}*\n"
            message += f"   Score: {score}/100 | Risk: {risk}\n"
            message += f"   Mdundo Listeners: {listeners:,}\n"
            for flag in artist['analysis']['flags']:
                message += f"   • {flag}\n"
            message += "\n"

        self._post_message(message)

    def _post_message(self, message: str):
        """Post message to Slack webhook"""
        try:
            data = {
                "text": message,
                "mrkdwn": True
            }
            response = requests.post(self.webhook, json=data, timeout=10)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ Slack post error: {e}")


def main():
    """Main execution"""
    print("\n" + "="*70)
    print("🔍 MDUNDO ACCURATE FRAUD DETECTION")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

    # Initialize
    scraper = MdundoAccurateScraper()
    spotify_checker = SpotifyChecker()
    detector = FraudDetector(spotify_checker)

    slack_webhook = os.getenv('SLACK_WEBHOOK')
    slack_poster = SlackPoster(slack_webhook) if slack_webhook else None

    countries = ["ng", "tz", "ke", "za", "ug", "gh", "cm"]
    all_results = {}

    for country in countries:
        print(f"\n{'─'*70}")
        print(f"Analyzing {country.upper()}")
        print(f"{'─'*70}")

        # Get chart data
        chart_data = scraper.get_chart_data(country, limit=50)

        if not chart_data:
            print(f"  ⚠️ No data for {country.upper()}\n")
            continue

        # Analyze each artist
        print(f"  🔎 Analyzing artists for fraud...")
        results = []

        for artist in chart_data:
            try:
                # Get artist details
                details = scraper.get_artist_details(artist['artist_id'], artist['artist_url'])
                artist.update(details)

                # Analyze
                analysis = detector.analyze_artist(artist)
                artist['analysis'] = analysis

                results.append(artist)

            except Exception as e:
                print(f"    ⚠️ Error analyzing {artist['artist_name']}: {e}")
                continue

        # Store results
        all_results[country.upper()] = results

        # Show summary
        flagged = [r for r in results if r['analysis']['risk_level'] != 'CLEAN']
        print(f"  ✅ Done: {len(results)} analyzed, {len(flagged)} flagged\n")

        # Post to Slack
        if slack_poster:
            print(f"  📤 Posting to Slack...")
            slack_poster.post_country_results(country.upper(), results)

    # Post summary
    if slack_poster:
        print(f"\n📊 Posting summary...")
        total_analyzed = sum(len(r) for r in all_results.values())
        total_flagged = sum(
            len([a for a in r if a['analysis']['risk_level'] != 'CLEAN'])
            for r in all_results.values()
        )

        summary = f"""
📊 *DAILY FRAUD DETECTION SUMMARY*
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S EAT')}

Total Analyzed: {total_analyzed}
Total Flagged: {total_flagged}

🔄 Next run: {(datetime.now()).strftime('%Y-%m-%d')} at 06:00 EAT
        """
        slack_poster._post_message(summary)

    print(f"\n{'='*70}")
    print("✅ FRAUD DETECTION COMPLETE")
    print(f"{'='*70}\n")

    # Save results
    with open('fraud_detection_results.json', 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print("💾 Results saved to fraud_detection_results.json")


if __name__ == "__main__":
    main()
