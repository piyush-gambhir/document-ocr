"""Render deterministic, visibly fictional OCR contract fixtures for all profiles.

These are generated from explicit answers, never from production extractors or
OCR output. They exercise image decoding, recognition and field extraction but
do not estimate real-document accuracy. No seals, portraits or official artwork
are copied. Pillow's bundled font avoids platform-dependent font downloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path('benchmark-data/samples')
MANIFEST = Path('benchmark-data/synthetic/manifest.json')
PROFILES = ('passport', 'pan', 'aadhaar', 'driving_licence', 'voter_id',
            'nrega_job_card', 'npr_letter', 'us_driver_license', 'us_state_id',
            'passport_card', 'us_green_card', 'us_ead', 'visa', 'us_i94', 'us_w9')
BLOCKS = {'passport': 'fields', 'pan': 'panFields', 'aadhaar': 'aadhaarFields',
          'driving_licence': 'drivingLicenceFields', 'voter_id': 'voterIdFields',
          'nrega_job_card': 'nregaJobCardFields', 'npr_letter': 'nprLetterFields'}


def check_digit(value: str) -> str:
    alphabet = '<0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    numbers = {char: (0 if char == '<' else int(char) if char.isdigit() else ord(char) - 55)
               for char in alphabet}
    return str(sum(numbers[char] * (7, 3, 1)[i % 3] for i, char in enumerate(value)) % 10)


def definition(kind: str, identity: int) -> dict:
    surname, given = (('SAMPLE', 'ANNA MARIA'), ('EXAMPLE', 'DEV ARUN'))[identity]
    name = given + ' ' + surname
    dob, iso, birth = (('15/03/1990', '1990-03-15', '900315'),
                       ('01/12/1992', '1992-12-01', '921201'))[identity]
    us_dob = ('03/15/1990', '12/01/1992')[identity]
    number = ('K1234567', 'R7654321')[identity]
    title, lines, mrz = [], [], []
    fields = {}
    if kind == 'passport':
        title = ['REPUBLIC OF INDIA', 'PASSPORT']
        lines = [('Surname', surname), ('Given Names', given), ('Passport Number', number),
                 ('Nationality', 'IND'), ('Date of Birth', dob), ('Sex', 'F'),
                 ('Date of Expiry', '01/06/2035')]
        first = ('P<IND' + surname + '<<' + given.replace(' ', '<')).ljust(44, '<')
        num = number.ljust(9, '<')
        second = num + check_digit(num) + 'IND' + birth + check_digit(birth) + 'F350601' + check_digit('350601')
        second += '<' * 14 + '0'
        second += check_digit(second[:10] + second[13:20] + second[21:43])
        mrz = [first, second]
        fields = dict(surname=surname, givenNames=given, passportNumber=number, nationality='IND',
                      dateOfBirth=birth, expiryDate='350601', sex='F', countryCode='IND')
    elif kind == 'pan':
        pan = ('ABCPA1234F', 'DEFPE5678G')[identity]
        title = ['INCOME TAX DEPARTMENT', 'GOVERNMENT OF INDIA']
        lines = [('Permanent Account Number', pan), ('Name', name),
                 ("Father's Name", 'MOHAN ' + surname), ('Date of Birth', dob)]
        fields = dict(panNumber=pan, name=name, fatherName='MOHAN ' + surname, dateOfBirth=dob)
    elif kind == 'aadhaar':
        title = ['GOVERNMENT OF INDIA', 'UNIQUE IDENTIFICATION AUTHORITY OF INDIA']
        printed = '9998 8877 7669' if identity == 0 else 'XXXX XXXX 1234'
        lines = [('', name), ('DOB', dob), ('', 'FEMALE'), ('', printed)]
        fields = dict(name=name, dateOfBirth=dob, gender='FEMALE')
        if identity == 0:
            fields.update(aadhaarNumber=printed, checksumValid=True)
        else:
            fields.update(aadhaarNumber=None, aadhaarMasked=True, aadhaarLast4='1234')
    elif kind == 'driving_licence':
        num = ('MH1220150012345', 'DL0420170054321')[identity]
        title = ['INDIAN UNION DRIVING LICENCE', 'TRANSPORT DEPARTMENT']
        lines = [('DL No', num), ('Name', name), ('Date of Birth', dob),
                 ('Date of Issue', '12/06/2017'), ('Valid Till', '11/06/2035'),
                 ('Blood Group', 'B+'), ('Class of Vehicle', 'LMV')]
        fields = dict(dlNumber=num, name=name, dateOfBirth=dob, issueDate='12/06/2017',
                      validityDate='11/06/2035', bloodGroup='B+', classOfVehicle='LMV')
    elif kind == 'voter_id':
        num = ('ABC1234567', 'DEF7654321')[identity]
        title = ['ELECTION COMMISSION OF INDIA', 'ELECTOR PHOTO IDENTITY CARD']
        lines = [('EPIC No', num), ("Elector's Name", name), ("Father's Name", 'MOHAN ' + surname),
                 ('Sex', 'FEMALE'), ('Date of Birth', dob)]
        fields = dict(epicNumber=num, name=name, relationName='MOHAN ' + surname,
                      gender='FEMALE', dateOfBirth=dob)
    elif kind == 'nrega_job_card':
        num = ('RJ-27-001-002-0008147/00', 'UP-65-001-003-0087670/01')[identity]
        title = ['MAHATMA GANDHI NREGA', 'JOB CARD']
        lines = [('Job Card No', num), ('Name of Head of Household', name),
                 ('Date of Registration', '14/03/2019'), ('Village', 'RAMPUR'),
                 ('Gram Panchayat', 'RAMPUR'), ('District', 'JAIPUR'), ('Category', 'SC')]
        fields = dict(jobCardNumber=num, headOfHousehold=name, registrationDate='14/03/2019',
                      village='RAMPUR', gramPanchayat='RAMPUR', district='JAIPUR', category='SC')
    elif kind == 'npr_letter':
        num = ('NPR/DL/2024/004217', 'NPR/DL/2024/004218')[identity]
        address = ('14 LAKE VIEW ROAD NEW DELHI 110019', '22 PARK ROAD NEW DELHI 110019')[identity]
        title = ['OFFICE OF THE REGISTRAR GENERAL INDIA', 'NATIONAL POPULATION REGISTER']
        lines = [('Reference No', num), ('Name of Resident', name), ('Address of Resident', address),
                 ('Date of Issue', '14/03/2024')]
        fields = dict(referenceNumber=num, name=name, address=address, pincode='110019', issueDate='14/03/2024')
    elif kind in ('us_driver_license', 'us_state_id', 'passport_card', 'us_green_card', 'us_ead'):
        titles = {'us_driver_license': ['CALIFORNIA DRIVER LICENSE'],
                  'us_state_id': ['VIRGINIA IDENTIFICATION CARD'],
                  'passport_card': ['UNITED STATES PASSPORT CARD'],
                  'us_green_card': ['UNITED STATES PERMANENT RESIDENT CARD'],
                  'us_ead': ['UNITED STATES EMPLOYMENT AUTHORIZATION']}
        title = titles[kind]
        lines = [('Surname', surname), ('Given Names', given), ('Date of Birth', us_dob),
                 ('Expiry Date', '06/01/2035'), ('Sex', 'F')]
        fields = dict(surname=surname, givenNames=given, dateOfBirth=iso, expiryDate='2035-06-01', sex='F')
        if kind in ('us_green_card', 'us_ead'):
            num, card = ('123456789', 'MSC0123456789') if identity == 0 else ('987654321', 'SRC0987654321')
            category = 'IR1' if kind == 'us_green_card' else 'C09'
            lines += [('USCIS', num), ('Card Number', card), ('Category', category), ('Country of Birth', 'INDIA')]
            fields.update(uscisNumber=num, cardNumber=card, category=category, countryOfBirth='IND')
        else:
            num = ('C12345678', 'D87654321')[identity]
            label = {'us_driver_license': 'License Number', 'us_state_id': 'ID Number', 'passport_card': 'Passport Card Number'}[kind]
            lines += [(label, num), ('Date of Issue', '06/01/2025')]
            fields.update(documentNumber=num, issueDate='2025-06-01')
    elif kind == 'visa':
        width = 44 if identity == 0 else 36
        title = ['UNITED STATES OF AMERICA', 'VISA']
        lines = [('Surname', surname), ('Given Names', given), ('Date of Birth', us_dob), ('Sex', 'F')]
        num = ('K12345678', 'R76543210')[identity]
        mrz = [('V<USA' + surname + '<<' + given.replace(' ', '<')).ljust(width, '<'),
               (num + check_digit(num) + 'IND' + birth + check_digit(birth) + 'F350601' + check_digit('350601')).ljust(width, '<')]
        fields = dict(surname=surname, givenNames=given, documentNumber=num, dateOfBirth=iso,
                      expiryDate='2035-06-01', nationality='IND', sex='F', mrzFormat='MRV_A' if width == 44 else 'MRV_B')
    elif kind == 'us_i94':
        num = ('123456789A1', '987654321B2')[identity]
        until = 'D/S' if identity == 0 else '06/01/2030'
        title = ['U.S. CUSTOMS AND BORDER PROTECTION', 'I-94 ARRIVAL/DEPARTURE RECORD']
        lines = [('Admission (I-94) Record Number', num), ('Family Name', surname),
                 ('First (Given) Name', given), ('Birth Date', us_dob), ('Class of Admission', 'F1'),
                 ('Admit Until Date', until), ('Most Recent Date of Entry', '08/01/2025')]
        fields = dict(i94Number=num, surname=surname, givenNames=given, dateOfBirth=iso,
                      classOfAdmission='F1', admitUntil='D/S' if identity == 0 else '2030-06-01', admissionDate='2025-08-01')
    elif kind == 'us_w9':
        title = ['FORM W-9', 'REQUEST FOR TAXPAYER', 'IDENTIFICATION NUMBER AND CERTIFICATION']
        label, tin, id_type = ('Social security number', '987-65-4321', 'ssn') if identity == 0 else ('Employer identification number', '12-3456789', 'ein')
        lines = [('1 Name', name), ('2 Business name', ''), ('5 Address', '123 MAIN STREET'),
                 ('6 City, state, and ZIP code', 'BOSTON MA 02108'), (label, tin)]
        fields = dict(name=name, businessName=None, address='123 MAIN STREET',
                      cityStatePostalCode='BOSTON MA 02108', taxpayerId=tin.replace('-', ''), taxpayerIdType=id_type)
    else:
        raise ValueError('unknown fixture profile')
    return dict(documentType=kind, fieldBlock=BLOCKS.get(kind, 'documentFields'),
                fields=fields, title=title, lines=lines, mrzRaw=mrz or None)


def render(definition: dict, *, variant: str = 'clean', negative: bool = False) -> Image.Image:
    kind = definition['documentType']
    portrait = kind in ('npr_letter', 'us_i94', 'us_w9', 'nrega_job_card')
    width, height = (1200, 1500) if portrait else (1600, 1000)
    canvas = Image.new('RGB', (width, height), (244, 244, 238))
    draw = ImageDraw.Draw(canvas)
    y = 48
    for title in definition['title']:
        font = ImageFont.load_default(size=38)
        if draw.textlength(title, font=font) > width - 120:
            font = ImageFont.load_default(size=30)
        draw.text((60, y), title, fill=(18, 28, 45), font=font)
        y += 62
    y += 40
    for label, value in definition['lines']:
        # A template with empty values is a negative, not a complete document.
        value = '' if negative else value
        text = label + (': ' if label else '') + value
        font = ImageFont.load_default(size=34)
        if draw.textlength(text, font=font) > width - 120:
            font = ImageFont.load_default(size=27)
        draw.text((60, y), text, fill=(12, 12, 12), font=font)
        y += 64
    if definition['mrzRaw'] and not negative:
        y = height - 215
        for line in definition['mrzRaw']:
            font = ImageFont.load_default(size=40)
            step = (width - 120) / len(line)
            for i, char in enumerate(line):
                draw.text((60 + i * step, y), char, fill=(10, 10, 10), font=font)
            y += 64
    draw.text((60, height - 50), 'SYNTHETIC OCR TEST - NOT A VALID DOCUMENT',
              font=ImageFont.load_default(size=22), fill=(50, 50, 50))
    if variant == 'tilted':
        return canvas.rotate(3, Image.Resampling.BICUBIC, expand=True, fillcolor=(214, 218, 221))
    if variant not in ('clean', 'jpeg'):
        raise ValueError('unknown capture variant')
    return canvas


def generate(root: Path = ROOT, manifest_path: Path = MANIFEST) -> dict:
    files, cases = [], []
    def record(path: str, raw: bytes):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        files.append(dict(path=path, kind='generated', bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))

    import io
    for kind in PROFILES:
        for identity in range(2):
            data = definition(kind, identity)
            group = f'synthetic-contract/{kind}/{identity}'
            truth_path = group + '/truth.json'
            record(truth_path, (json.dumps(data, sort_keys=True) + '\n').encode())
            for variant in ('clean', 'tilted', 'jpeg'):
                path = group + '/' + variant + ('.jpg' if variant == 'jpeg' else '.png')
                encoded = io.BytesIO()
                render(data, variant=variant).save(encoded, format='JPEG' if variant == 'jpeg' else 'PNG', **({'quality': 65} if variant == 'jpeg' else {}))
                record(path, encoded.getvalue())
                cases.append(dict(id=group + '/' + variant, group=group, dataset='synthetic-contract',
                                  profile=kind, image=path, truth=truth_path, fieldBlock=data['fieldBlock'],
                                  split='synthetic_contract', capture=variant))
        group = 'synthetic-contract/blank/' + kind
        path, truth_path = group + '.png', group + '.json'
        encoded = io.BytesIO()
        render(definition(kind, 0), negative=True).save(encoded, format='PNG')
        record(path, encoded.getvalue())
        record(truth_path, b'{"fields": {}, "accepted": false}\n')
        cases.append(dict(id=group, group=group, dataset='synthetic-contract', profile='negative_control',
                          targetProfile=kind, image=path, truth=truth_path, split='synthetic_contract', capture='blank'))
    manifest = dict(schemaVersion=1, purpose='Synthetic image contract coverage; not real-world accuracy or independent public identities.',
                    generatorSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), files=files, cases=cases)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    args = parser.parse_args()
    manifest = generate(args.root, args.manifest)
    print(json.dumps({'cases': len(manifest['cases']), 'profiles': len(PROFILES),
                      'bytes': sum(f['bytes'] for f in manifest['files']), 'manifest': str(args.manifest)}))


if __name__ == '__main__':
    main()
