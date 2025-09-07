import json
import re

from salmon.errors import ScrapeError

from .base import BaseScraper


class iTunesBase(BaseScraper):
    url = "https://itunes.apple.com"
    site_url = "https://music.apple.com"
    search_url = "https://itunes.apple.com/search"
    regex = re.compile(r"^https?://(itunes|music)\.apple\.com/(?:(\w{2,4})/)?album/(?:[^/]*/)?([^\?]+)")
    release_format = "/album/-/{rls_id}"
    get_params = {"country": "us", "lang": "en-US"}

    async def create_soup(self, url, params=None):
        """
        Override create_soup to use iTunes Lookup API instead of HTML scraping.
        Extract album ID from the URL and fetch JSON data from iTunes API.
        """
        try:
            # Extract album ID from the URL
            match = self.regex.match(url)
            if not match:
                raise ScrapeError("Invalid iTunes URL format")

            album_id = match.group(3)
            # Remove any trailing characters that might not be part of the ID
            album_id = album_id.split("?")[0].split("/")[0]

            # First, get the album info
            album_api_url = f"/lookup?id={album_id}&entity=album"
            album_data = await self.get_json(album_api_url, params=params)

            if not album_data.get("results"):
                raise ScrapeError("No results found from iTunes API for album")

            album_info = album_data["results"][0]

            # Then get the track listing with entity=song
            tracks_api_url = f"/lookup?id={album_id}&entity=song"
            tracks_data = await self.get_json(tracks_api_url, params=params)

            # Combine album info with track data
            result = {
                "album_info": album_info,
                "tracks": tracks_data.get("results", [])[1:] if tracks_data.get("results") else [],
                # Skip first result as it's the album info again
            }

            return result

        except (IndexError, KeyError, AttributeError) as e:
            raise ScrapeError("Failed to parse iTunes URL or API response") from e
        except json.JSONDecodeError as e:
            raise ScrapeError("iTunes API did not return valid JSON") from e
