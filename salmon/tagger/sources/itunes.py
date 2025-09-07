import re
from collections import defaultdict

from salmon.common import RE_FEAT, parse_copyright
from salmon.errors import ScrapeError
from salmon.sources import iTunesBase
from salmon.tagger.sources.base import MetadataMixin

ALIAS_GENRE = {
    "Hip-Hop/Rap": {"Hip Hop", "Rap"},
    "R&B/Soul": {"Rhythm & Blues", "Soul"},
    "Music": {},  # Aliasing Music to an empty set because we don't want a genre 'music'
}


class Scraper(iTunesBase, MetadataMixin):
    def parse_release_title(self, data):
        """Parse release title from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            title = album_data.get("collectionName", "").strip()
            if not title:
                raise ScrapeError("No collection name found in iTunes API response")
            return RE_FEAT.sub("", title)
        except (TypeError, KeyError) as e:
            raise ScrapeError("Failed to parse release title from iTunes API") from e

    def parse_cover_url(self, data):
        """Parse cover URL from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            # iTunes API provides artwork URLs in different sizes
            # artworkUrl100, artworkUrl60, etc. Get the highest resolution available
            artwork_url = album_data.get("artworkUrl100")
            if artwork_url:
                # Replace the size parameter to get higher resolution if available
                artwork_url = artwork_url.replace("100x100", "1000x1000")
            return artwork_url
        except (TypeError, KeyError) as e:
            raise ScrapeError("Could not parse cover URL from iTunes API") from e

    def parse_genres(self, data):
        """Parse genres from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            primary_genre = album_data.get("primaryGenreName", "")
            genres = set()
            if primary_genre:
                # Apply alias mapping or use the original genre
                aliased_genres = ALIAS_GENRE.get(primary_genre, {primary_genre})
                genres.update(aliased_genres)
            return genres
        except (TypeError, KeyError) as e:
            raise ScrapeError("Could not parse genres from iTunes API") from e

    def parse_release_year(self, data):
        """Parse release year from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            release_date = album_data.get("releaseDate", "")
            if release_date:
                # releaseDate format: "2023-01-01T08:00:00Z"
                year_match = re.search(r"(\d{4})", release_date)
                if year_match:
                    return int(year_match.group(1))
            raise ScrapeError("No valid release date found")
        except (TypeError, ValueError) as e:
            raise ScrapeError("Could not parse release year from iTunes API") from e

    def parse_release_type(self, data):
        """Parse release type from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            collection_name = album_data.get("collectionName", "").strip()
            track_count = album_data.get("trackCount", 0)

            # Check for explicit type indicators in the title
            if re.match(r".*\sEP$", collection_name, re.IGNORECASE):
                return "EP"
            if re.match(r".*\sSingle$", collection_name, re.IGNORECASE):
                return "Single"

            # Infer type from track count if no explicit indicator
            if track_count == 1:
                return "Single"
            elif track_count <= 6:
                return "EP"
            else:
                return "Album"
        except (TypeError, KeyError) as e:
            raise ScrapeError("Could not parse release type from iTunes API") from e

    def parse_release_date(self, data):
        """Parse release date from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            release_date = album_data.get("releaseDate", "")
            if release_date:
                # Format: "2023-01-01T08:00:00Z" -> "2023-01-01"
                return release_date.split("T")[0]
            return None
        except (TypeError, KeyError):
            return None

    def parse_release_label(self, data):
        """Parse record label from iTunes API JSON data."""
        try:
            album_data = data.get("album_info", data)
            # iTunes API doesn't always provide label info directly
            # We can try to get it from copyright string if available
            copyright_text = album_data.get("copyright", "")
            if copyright_text:
                return parse_copyright(copyright_text)

            # Fallback to artist name if no label info
            artist_name = album_data.get("artistName", "Unknown")
            return artist_name
        except (TypeError, KeyError) as e:
            raise ScrapeError("Could not parse record label from iTunes API") from e

    def parse_comment(self, data):
        """Parse comment/description from iTunes API JSON data."""
        # iTunes API typically doesn't provide description in the lookup endpoint
        # This would require additional API calls or web scraping
        return None

    def parse_tracks(self, data):
        """Parse tracks from iTunes API JSON data."""
        tracks = defaultdict(dict)
        cur_disc = 1

        try:
            # Check if we have detailed track data
            track_list = data.get("tracks", [])

            if track_list:
                # We have detailed track information
                for track in track_list:
                    if track.get("wrapperType") == "track":
                        track_num = track.get("trackNumber", 0)
                        disc_num = track.get("discNumber", 1)

                        if track_num > 0:
                            raw_title = track.get("trackName", "").strip()
                            title = RE_FEAT.sub("", raw_title)

                            # Parse artists - main artist from artistName
                            artists = []
                            artist_name = track.get("artistName", "")
                            if artist_name:
                                artists.append((artist_name, "main"))

                            # Parse guest artists from track title if present
                            feat_match = RE_FEAT.search(raw_title)
                            if feat_match:
                                guest_artists = self._parse_guest_artists(feat_match.group(1))
                                for artist in guest_artists:
                                    if (artist, "guest") not in artists:
                                        artists.append((artist, "guest"))

                            tracks[str(disc_num)][track_num] = self.generate_track(
                                trackno=track_num,
                                discno=disc_num,
                                artists=artists,
                                title=title,
                            )
            else:
                # Fallback: use album info to create placeholder tracks
                album_data = data.get("album_info", data)
                track_count = album_data.get("trackCount", 0)

                if track_count == 0:
                    raise ScrapeError("No tracks found in iTunes API response")

                for track_num in range(1, track_count + 1):
                    tracks[str(cur_disc)][track_num] = self.generate_track(
                        trackno=track_num,
                        discno=cur_disc,
                        artists=[],  # Would need additional API call to get track-specific artists
                        title=f"Track {track_num}",  # Placeholder - would need additional API call
                    )

            return dict(tracks)

        except (TypeError, KeyError, ValueError) as e:
            raise ScrapeError("Could not parse tracks from iTunes API") from e

    def _parse_guest_artists(self, artist_string):
        """Parse guest artists from a feature string."""
        artists = []
        # Split by common separators and clean up
        separators = [" & ", " and ", ", ", " feat. ", " ft. ", " featuring "]

        # Replace all separators with a common one for splitting
        normalized = artist_string
        for sep in separators:
            normalized = normalized.replace(sep, " | ")

        for artist in normalized.split(" | "):
            artist = artist.strip()
            if artist and artist not in artists:
                artists.append(artist)

        return artists
