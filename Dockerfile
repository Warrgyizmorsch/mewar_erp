# Python ka base image le rahe hain
FROM python:3.10

# Kaam karne ke liye ek folder banaya
WORKDIR /code

# Requirements file copy karke libraries install ki
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Baaki saara code copy kiya
COPY . /code

# Hugging Face humesha Port 7860 par listen karta hai (Ye sabse zaroori hai!)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]