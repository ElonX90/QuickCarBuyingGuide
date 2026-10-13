import copy
import importlib.util
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('build',Path(__file__).resolve().parents[1]/'scripts'/'build.py')
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models,cls.brands,cls.sources,cls.config=build.load()

    def test_unknowns_cannot_become_a_zero_score_or_pass(self):
        m=copy.deepcopy(self.models[0])
        b=copy.deepcopy(self.brands[0])
        m['development']['months_range']=None
        m['globalization']['level']='unknown'
        m['sku']['count_range']=None
        b['recall_status']='not_verified'
        b['labor_status']='not_verified'
        result=build.score(m,b,self.config)
        self.assertEqual((result['low'],result['high']),(0,100))
        self.assertEqual(result['status'],'购前条件待核')

    def test_cycle_direction_and_interval_endpoints(self):
        self.assertEqual(build.cycle_points(15,self.config),100)
        self.assertAlmostEqual(build.cycle_points(24,self.config),66.6666666667)
        self.assertEqual(build.cycle_points(36,self.config),0)
        m=copy.deepcopy(self.models[0])
        m['development']['months_range']=[23,25]
        endpoints=build.components(m,self.brands[0],self.config)['development']
        self.assertLess(endpoints[0],endpoints[1])
        self.assertAlmostEqual(endpoints[0],100*11/18)

    def test_sku_lower_bound_is_sufficient_only_in_top_band(self):
        m=copy.deepcopy(self.models[0])
        m['sku']['count_range']=[12,None]
        self.assertEqual(build.components(m,self.brands[0],self.config)['sku'],(100,100))
        m['sku']['count_range']=[4,None]
        self.assertEqual(build.components(m,self.brands[0],self.config)['sku'],(30,100))

    def test_old_cycle_and_future_plan_do_not_pass_current_model(self):
        m=next(m for m in self.models if m['id']=='li_l6')
        self.assertIsNone(m['development']['months_range'])
        x=next(m for m in self.models if m['id']=='xiaomi_su7')
        b=next(b for b in self.brands if b['id']==x['brand_id'])
        self.assertEqual(build.components(x,b,self.config)['globalization'],(0,100))

    def test_powertrain_evidence_is_not_inherited(self):
        pure=next(m for m in self.models if m['id']=='xpeng_p7_bev')
        extended=next(m for m in self.models if m['id']=='xpeng_p7_erev')
        self.assertNotEqual(pure['globalization']['level'],extended['globalization']['level'])

    def test_bad_weights_and_missing_source_are_rejected(self):
        bad=copy.deepcopy(self.config)
        bad['weights']['development']=41
        with self.assertRaises(ValueError):
            build.validate(self.models,self.brands,self.sources,bad)
        models=copy.deepcopy(self.models)
        models[0]['sale_sources']=['does_not_exist']
        with self.assertRaises(ValueError):
            build.validate(models,self.brands,self.sources,self.config)

    def test_no_brand_is_marked_currently_underpaying_without_evidence(self):
        self.assertTrue(all(b['labor_status']=='not_verified' for b in self.brands))


    def test_outsourcing_objection_cannot_be_offset_by_full_payment(self):
        m=copy.deepcopy(self.models[0])
        b=copy.deepcopy(self.brands[0])
        b['labor_status']='verified_full_scope'
        b['outsourcing_status']='verified_present'
        self.assertEqual(build.components(m,b,self.config)['labor'],(100,100))
        result=build.score(m,b,self.config)
        self.assertIn('不建议购买',result['status'])

    def test_absence_of_outsourcing_cannot_be_assumed_from_payment(self):
        b=copy.deepcopy(self.brands[0])
        b['labor_status']='verified_full_scope'
        b['outsourcing_status']='not_verified'
        result=build.score(self.models[0],b,self.config)
        self.assertEqual(result['component_bounds']['labor'],(0,100))
        self.assertIn('当前用工主体无外包/派遣员工',result['missing_prerequisites'])

    def test_pending_or_conflicting_sources_cannot_change_published_scores(self):
        for status in ['pending','conflicting','rejected']:
            sources=copy.deepcopy(self.sources)
            source_id=self.models[0]['sale_sources'][0]
            next(s for s in sources if s['id']==source_id)['review']['status']=status
            with self.assertRaises(ValueError):
                build.validate(self.models,self.brands,sources,self.config)

    def test_outsourcing_findings_require_evidence_entity_period_and_scope(self):
        brands=copy.deepcopy(self.brands)
        brands[0]['outsourcing_status']='verified_present'
        with self.assertRaises(ValueError):
            build.validate(self.models,brands,self.sources,self.config)


    def test_monthly_cohort_must_not_mix_year_or_omit_models(self):
        cohort=build.validate_cohort(self.models,self.sources,self.config)
        old=copy.deepcopy(cohort)
        old['month']='2025-09'
        with self.assertRaises(ValueError):
            build.validate_cohort(self.models,self.sources,self.config,old)
        incomplete=copy.deepcopy(cohort)
        incomplete['rows'].pop()
        with self.assertRaises(ValueError):
            build.validate_cohort(self.models,self.sources,self.config,incomplete)

    def test_monthly_cohort_rejects_duplicate_rank_and_orphan_mapping(self):
        cohort=build.validate_cohort(self.models,self.sources,self.config)
        duplicate=copy.deepcopy(cohort)
        duplicate['rows'][1]['rank']=1
        with self.assertRaises(ValueError):
            build.validate_cohort(self.models,self.sources,self.config,duplicate)
        orphan=copy.deepcopy(cohort)
        orphan['rows'][0]['observation_ids']=['missing_model']
        with self.assertRaises(ValueError):
            build.validate_cohort(self.models,self.sources,self.config,orphan)


    def test_manufacturer_mapping_cannot_use_pending_evidence(self):
        models=copy.deepcopy(self.models)
        sources=copy.deepcopy(self.sources)
        sid=models[0]['sale_sources'][0]
        next(s for s in sources if s['id']==sid)['review']['status']='pending'
        models[0]['sale_sources']=[self.models[1]['sale_sources'][0]]
        models[0]['manufacturer_mapping_sources']=[sid]
        with self.assertRaises(ValueError):
            build.validate(models,self.brands,sources,self.config)

    def test_labor_payment_claim_needs_subject_period_and_scope(self):
        brands=copy.deepcopy(self.brands)
        brands[0]['labor_status']='verified_full_scope'
        brands[0]['labor_sources']=[self.sources[0]['id']]
        with self.assertRaises(ValueError):
            build.validate(self.models,brands,self.sources,self.config)


if __name__=='__main__':
    unittest.main()
