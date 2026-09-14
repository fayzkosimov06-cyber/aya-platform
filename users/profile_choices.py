"""Shared fixed choices for profiles and search. Historical data is preserved."""
COURSE_CHOICES = [(n, str(n)) for n in range(1, 7)]
FACULTY_CHOICES = [(n, n) for n in (
    'Лечебный', 'Стоматологический', 'Педиатрический',
    'Фармацевтический', 'Медико-профилактический',
)]
CITY_CHOICES = [(n, n) for n in (
    'Бохтар', 'Бустон', 'Вахдат', 'Гиссар', 'Гулистон', 'Душанбе',
    'Истаравшан', 'Истиклол', 'Исфара', 'Канибадам', 'Куляб',
    'Левакант', 'Нурек', 'Пенджикент', 'Рогун', 'Турсунзаде', 'Худжанд', 'Хорог',
)]

def filter_profiles(queryset, params):
    for field, choices in [('course', COURSE_CHOICES), ('faculty', FACULTY_CHOICES), ('city', CITY_CHOICES)]:
        value = params.get(field, '')
        if value:
            if value not in {str(key) for key, _ in choices}:
                return queryset.none()
            queryset = queryset.filter(**{field: value})
    return queryset

def filter_choices():
    return {'faculties': [v for v, _ in FACULTY_CHOICES],
            'courses': [v for v, _ in COURSE_CHOICES],
            'cities': [v for v, _ in CITY_CHOICES]}
