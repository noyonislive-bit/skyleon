# cPanel-এ Skyloon AI চালু করা (সবসময় অনলাইন)

এই ধাপগুলো শেষ করলে ওয়েবসাইট আপনার নিজের ডোমেইনে ২৪ ঘণ্টা চলবে — Claude-এর সেশন বা কারো কম্পিউটার চালু থাকা লাগবে না।
মোট সময় লাগে প্রায় ২০–৩০ মিনিট। বিস্তারিত (ইংরেজি) রেফারেন্স: [`DEPLOY_CPANEL.md`](DEPLOY_CPANEL.md)।

**যা লাগবে:** cPanel হোস্টিং যেখানে **Setup Python App** আর **Terminal** আছে (Python 3.10 বা নতুন), আপনার ডোমেইন,
আর SSL (cPanel-এর ফ্রি AutoSSL-ই যথেষ্ট)।

---

## ধাপ ১ — ডেটাবেস বানান

cPanel → **MySQL® Databases**

1. *Create New Database*: যেমন `skyloon` → cPanel নামের আগে আপনার ইউজারনেম বসিয়ে দেবে (যেমন `cpuser_skyloon`)।
2. *Add New User*: একটা ইউজার আর শক্ত পাসওয়ার্ড (পাসওয়ার্ডটা লিখে রাখুন)।
3. *Add User To Database*: ইউজারটা ডেটাবেসে যোগ করে **ALL PRIVILEGES** টিক দিন → *Make Changes*।

## ধাপ ২ — কোড আপলোড করুন

সবচেয়ে সহজ উপায় (ZIP):

1. GitHub-এ রিপোজিটরি খুলুন → ব্রাঞ্চ **`claude/eager-cori-wcmlyv`** বেছে নিন → **Code → Download ZIP**।
2. cPanel → **File Manager** → আপনার হোম ফোল্ডারে (`/home/<cpuser>/`, **public_html-এর ভেতরে নয়**) ZIP আপলোড করুন →
   ডান-ক্লিক → **Extract**।
3. যে ফোল্ডার তৈরি হলো (যেমন `skyleon-claude-eager-cori-wcmlyv`) সেটার নাম বদলে **`skyloon`** রাখুন।

> Git দিয়েও করা যায়: cPanel → *Git™ Version Control* → *Create* → রিপোজিটরির লিংক দিয়ে `/home/<cpuser>/skyloon`-এ clone।
> রিপোজিটরি private হলে GitHub-এ একটা deploy key লাগবে — ZIP পদ্ধতিতে সেটা লাগে না।

## ধাপ ৩ — Python অ্যাপ তৈরি করুন

cPanel → **Setup Python App** → **Create Application**

| ঘর | কী দেবেন |
|---|---|
| Python version | 3.11 (বা 3.10-এর বেশি যেটা আছে) |
| Application root | `skyloon` |
| Application URL | আপনার ডোমেইন |
| Application startup file | `passenger_wsgi.py` |
| Application Entry point | `application` |

**Create** চাপুন। পেজের উপরে একটা কমান্ড দেখাবে, অনেকটা এরকম — এটা কপি করুন:

```bash
source /home/cpuser/virtualenv/skyloon/3.11/bin/activate && cd /home/cpuser/skyloon
```

## ধাপ ৪ — এক কমান্ডে ইনস্টল

cPanel → **Terminal** খুলুন। আগের ধাপের কমান্ডটা পেস্ট করে Enter দিন, তারপর:

```bash
bash deploy/cpanel_install.sh
```

ইনস্টলার কয়েকটা প্রশ্ন করবে — উত্তর দিন:

- আপনার ডোমেইন (যেমন `skyloon.ai`)
- ধাপ ১-এর ডেটাবেসের নাম, ইউজার আর পাসওয়ার্ড
- ইমেইল: SMTP হোস্ট, মেইলবক্স (যেমন `no-reply@আপনার-ডোমেইন`) আর তার পাসওয়ার্ড
  (মেইলবক্স না থাকলে আগে cPanel → *Email Accounts*-এ বানিয়ে নিন)
- নতুন কোটেশন / আবেদনের নোটিফিকেশন কোন ইমেইলে যাবে
- শেষে আপনার **Super Admin** লগইন (ইমেইল, নাম, পাসওয়ার্ড)

বাকি সব সে নিজেই করবে: প্যাকেজ ইনস্টল, `.env` সেটিংস, ডেটাবেস টেবিল, CSS/JS, cron job আর অ্যাপ রিস্টার্ট।

## ধাপ ৫ — HTTPS চালু করুন

cPanel → **Domains** → আপনার ডোমেইনের পাশে **Force HTTPS Redirect** চালু করুন।

## ধাপ ৬ — দেখে নিন

- `https://আপনার-ডোমেইন/` — পাবলিক ওয়েবসাইট
- `https://আপনার-ডোমেইন/admin/` — অ্যাডমিন প্যানেল (Super Admin দিয়ে লগইন)
- `https://আপনার-ডোমেইন/login/` — কর্মীদের লগইন

তারপর **Admin → Settings**-এ কোম্পানির আসল ইমেইল, ফোন, ঠিকানা আর সোশ্যাল লিংক বসিয়ে দিন।

## নমুনা ডেটা (ঐচ্ছিক)

ইনস্টলার জিজ্ঞেস করবে নমুনা ডেটা যোগ করবেন কিনা — প্রিভিউতে যা দেখেছেন সেটাই: ৩টা প্রজেক্ট, টিউটোরিয়াল,
টেস্ট, ফিডব্যাক, ওয়ার্ক গাইড, প্র্যাকটিস টাস্ক আর নমুনা কর্মী অ্যাকাউন্ট (`pm@`, `trainer@`,
`employee1..8@skyleon.local`)। তাহলে শুরু থেকেই প্রতিটা পেজে কিছু না কিছু দেখা যাবে।
নমুনা অ্যাকাউন্টের পাসওয়ার্ড আপনি নিজে ঠিক করে দেবেন; লাইভ সাইটে বাড়তি কোনো Super Admin তৈরি হয় না।

- পরে যোগ করতে: `python manage.py seed_demo --password 'নিজের-শক্ত-পাসওয়ার্ড'`
- আসল কর্মীরা যোগ দেওয়ার আগে মুছে ফেলতে: `python manage.py seed_demo --remove` — আপনার নিজের ডেটা থাকবে।

> ইনস্টলার যদি বলে *“crontab is not available”*, তাহলে cPanel → **Cron Jobs**-এ এই দুটো যোগ করুন
> (পাথ আপনার ধাপ ৩-এর কমান্ড অনুযায়ী বদলাবেন):
>
> - প্রতি ৫ মিনিটে: `/home/cpuser/virtualenv/skyloon/3.11/bin/python /home/cpuser/skyloon/manage.py process_emails >/dev/null 2>&1`
> - প্রতিদিন ০৩:১৫-এ: `/home/cpuser/virtualenv/skyloon/3.11/bin/python /home/cpuser/skyloon/manage.py cleanup >/dev/null 2>&1`

---

## পরে আপডেট করা

নতুন কোড এলে (নতুন ZIP এক্সট্র্যাক্ট করে বা `git pull` দিয়ে) Terminal-এ ধাপ ৩-এর কমান্ড চালিয়ে:

```bash
bash deploy/cpanel_update.sh
```

ZIP দিয়ে আপডেট করলে পুরোনো ফোল্ডারের **`.env`** ফাইলটা নতুন ফোল্ডারে কপি করতে ভুলবেন না।

## সমস্যা হলে

| যা দেখছেন | যা করবেন |
|---|---|
| “Can't connect to the database” | ধাপ ১ আবার দেখুন — ইউজার ডেটাবেসে যোগ হয়েছে কিনা আর **ALL PRIVILEGES** দেওয়া কিনা। `.env`-এর `DB_*` ঠিক আছে কিনা। |
| পেজে 500 / “Incomplete response” | অ্যাপ ফোল্ডারের `stderr.log` আর `~/logs/skyloon.log` দেখুন। আপডেটের পর হলে `bash deploy/cpanel_update.sh` আবার চালান। |
| ফর্মে “CSRF” / “পেজের মেয়াদ শেষ” | `.env`-এ `CSRF_TRUSTED_ORIGINS`-এ `https://আপনার-ডোমেইন` আর `https://www.আপনার-ডোমেইন` আছে কিনা দেখুন। |
| ইমেইল যাচ্ছে না | Admin → **Email log** দেখুন; `.env`-এর `EMAIL_*` মিলিয়ে নিন; cPanel → *Email Deliverability*-তে SPF/DKIM ঠিক করুন। |
| কিছু বদলালেন কিন্তু দেখাচ্ছে না | Setup Python App → **Restart** (বা `touch tmp/restart.txt`)। |

ভিডিও বেশি হলে হোস্টিংয়ের ডিস্ক ভরে যেতে পারে — তখন Cloudflare R2 বা Backblaze B2-এর মতো স্টোরেজ ব্যবহার করুন
(সেটিংস: [`DEPLOY_CPANEL.md` → Video storage](DEPLOY_CPANEL.md))।
