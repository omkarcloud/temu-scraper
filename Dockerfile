FROM chetan1111/botasaurus:chrome-151

ENV PYTHONUNBUFFERED=1
# Never open debug prompts/devtools on crash.
ENV ENV=production

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# The image ships real Google Chrome + Xvfb. Chrome runs for about 30 seconds
# to earn a trusted Temu guest (and for search page 2+ and reviews); product,
# search and category pages then run over plain HTTP. Temu often distrusts
# data-center IPs — if the container's calls fail with "captcha", set
# TEMU_PROXY to a sticky residential proxy or run the scraper on your desktop
# (python run.py) instead.
CMD ["python", "run.py"]
