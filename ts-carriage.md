# AV1 specification for TS

Jean Baptiste Kempf (jb@videolan.org)  
Kieran Kunhya (kierank@obe.tv)  
Adrien Maglo (adrien@videolabs.io)  
Christophe Massiot (cmassiot@openheadend.tv)  
Mathieu Monnier (m.monnier@ateme.com)  
Mickael Raulet (m.raulet@ateme.com)

ATEME, OpenHeadend, Open Broadcast Systems, Videolabs, Videolan

DVB meeting 11/12 dec 2018<

## TODO today

* Identifier
* Descriptor
* Buffer Size and Rate mbn
* TU, OBU
* How to pack/StartCode emulation
* RAP
* Signal HRD (incomplete need SEI?)
* DTS on frames that are not shown
* Wording around unifying the model between AV1 and TS
* Signal UHD? (for HW decoders with limited capabilities like several hw decoding chips but only one able to decode UHD) - done in the level

## Identifier

'AV1 ' <A-V-1-space>

## Descriptor

Need to register format_identifier (SMPTE) *and* EN 300 468 Private data specifier descriptor

https://smpte-ra.org/mpeg-ts-ids


### Registration descriptor

descriptor_tag = 8  
descriptor_length = 8  
AV-1 --> FIXME you decide

### Definitions

 * **AV1 access unit**: a Decodable Frame Group as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

### AV1 video descriptor

> Need to use DVB private data specifier descriptor beforehands, with a private data specifier registered from https://www.dvbservices.com/identifiers/private_data_spec_id.  
> Requested 07-12-2018

For an AV1 video stream, the AV1 video descriptor provides basic information for identifying coding parameters, such as profile and level parameters of that AV1 video stream.

| Syntax                           | No. Of bits | Mnemonic   |
|:---------------------------------|:-----------:|:----------:|
| AV1_descriptor() {               |             |            |
|       **descriptor_tag**         | **8**       | **uimsbf** |
|       **descriptor_length**      | **8**       | **uimsbf** |
|       **seq_profile**            | **3**       | **uimsbf** |
|       **seq_level_idx_0**        | **5**       | **uimsbf** |
|       **seq_tier_0**             | **1**       | **bslbf**  |
|       **high_bitdepth**          | **1**       | **bslbf**  |
|       **twelve_bit**             | **1**       | **bslbf**  |
|       **monochrome**             | **1**       | **bslbf**  |
|       **chroma_subsampling_x**   | **1**       | **bslbf**  |
|       **chroma_subsampling_y**   | **1**       | **bslbf**  |
|       **chroma_sample_position** | **2**       | **uimsbf** |
|       **hdr_wcg_idc**            | **2**       | **uimsbf** |
|       **reserved**               | **6**       | **bslbf** |
| }                                |             |            |

### Semantic definition of fields in AV1 video descriptor

**seq_profile**, **seq_level_idx_0** and **high_bitdepth** - These fields shall be coded according to the semantics defined in AV1 Bitstream and Decoding Process Specification.

**seq_tier_0**, **twelve_bit**, **monochrome**, **chroma_subsampling_x**, **chroma_subsampling_y**, **chroma_sample_position** - These fields shall be coded according to the same semantics when they are present. If they are not present, they will be coded using the value inferred by the semantics.

**hdr_wcg_idc** - The value of this syntax element indicates the presence or absence of high dynamic range (HDR) and/or wide color gamut (WCG) video components in the associated PID according to Table 2-112. HDR is defined to be video that has high dynamic range if the video stream EOTF is higher than the Rec. ITU-R BT.1886 reference EOTF. WCG is defined to be video that is coded using colour primaries with a colour gamut not contained within Rec. ITU-R BT.709.

> Do we add the bit about at least 10 bits being mandatory for HDR ? 

| **hdr_wcg_idc** | **Description** |
|:---------------:|:----------------|
| 0               | SDR, i.e., video is based on the Rec. ITU-R BT.1886 reference EOTF with a color gamut that is contained within Rec. ITU-R BT.709 with a Rec. ITU-R BT.709 container |
| 1               | WCG only, i.e., video color gamut in a Rec ITU-R BT.2020 container that exceeds Rec. ITU-R BT.709  |
| 2               | Both HDR and WCG are to be indicated in the stream |
| 3               | No indication made regarding HDR/WCG or SDR characteristics of the stream  |

**reserved** - Will be set to ones.

### Carriage of AV1

#### Constraints for the transport of AV1

For AV1 video streams, the following constraints additionally apply:
 * An AV1 vidoe stream conforming to a profile defined in Annex A of AV1 Bitstream & Decoding Process Specification shall be an element of a Rec. ITU-T H.222.0 | ISO/IEC 13818-1 program and the stream_type for this elementary stream shall be equal to 0xBD (private_stream_1)
 * The sequence_header_obu as specified in AV1 Bitstream & Decoding Process Specification, that are necessary for decoding an AV1 video stream shall be present within the elementary stream carrying that AV1 video stream

#### Carriage in PES packets

AV1 Bitstream & Decoding Process Specification video is carried in PES packets as PES_packet_data_bytes, using one of the 16 stream_id values assigned to video, while signalling the AV1 Bitstream & Decoding Process Specification video stream, by means of the assigned stream-type value in the PMT (see Table 2-34). The highest level that may occur in an AV1 video stream, as well as a profile and tier that the entire stream conforms to should be signalled using the AV1 video descriptor. If an AV1 video descriptor is associated with an AV1 video stream, then this descriptor shall be conveyed in the descriptor loop for the respective elementary stream entry in the program map table. This Recommendation | International Standard does not specify the presentation of AV1 Bitstream & Decoding Process Specification streams in the context of a program stream. 

For PES packetization, no specific data alignment constraints apply, except when random_access_indicator is set to 1. When it is set, a PES_packet shall start, and in its header, data_alignement_indicator shall be set to 1.

For synchronization and STD management, PTSs and, when appropriate, DTSs are encoded in the header of the PES packet that carries the AV1 Bitstream & Decoding Process Specification video elementary stream data. For PTS and DTS encoding, the constraints and semantics apply as defined in 2.4.3.7 and 2.7. AV1 access unit that is not shown will not have a PTS or a DTS encoded in their PES header.

> There are explicit references to ITU-T H.222.0 specification. Do we keep them ?

#### Buffer Pool management

Carriage of an AV1 video stream over Rec. ITU-T H.222.0 | ISO/IEC 13818-1 does not impact the size of the Buffer Pool. For decoding of an AV1 video stream in the STD, the size of the Buffer Pool is as defined in AV1 Bitstream & Decoding Process Specification. The Buffer Pool shall be managed as specified in Annex E of AV1 Bitstream & Decoding Process Specification. A decoded AV1 access unit enters the Buffer Pool instantaneously upon decoding the AV1 access unit, hence at the Scheduled Removal Timing of the AV1 access unit. A decoded AV1 access unit is presented at the Presentation Time. If the AV1 video stream provides insufficient information to determine the Scheduled Removal Timing and the Presentation Time of AV1 access units, then these time instants shall be determined in the STD model from PTS and DTS timestamps as follows:
 1. The Scheduled Removal Timing of AV1 access unit n is the instant in time indicated by DTS(n) where DTS(n) is the DTS value of AV1 access unit n.
 2. The Presentation Time of AV1 access unit n is the instant in time indicated by PTS(n) where PTS(n) is the PTS value of AV1 access unit n.

#### T-STD Extensions for AV1

When there is an AV1 video stream in an Rec. ITU-T H.222.0 | ISO/IEC 13818-1 program, the T-STD model as described in 2.4.2.1 is extended as illustrated in figure X-YY and as specified below.

> TODO : Diagram similar to T-REC-H.222.0-201703-S!!PDF-E.pdf 2.17.2

##### TB<sub>n</sub>, MB<sub>n</sub>, EB<sub>n</sub> buffer management

The following additional notations are used to describe the T-STD extensions and are illustrated in Figure X-YY.  

| Notation | Definition |
|:--|:--|
| t(i) | indicates the time in seconds at which the i-th byte of the transport stream enters the system target decoder |
| TB<sub>n</sub> | is the transport buffer for elementary stream n |
| TBS | is the size of the transport buffer TBn, measured in bytes |
| MB<sub>n</sub> | is the multiplexing buffer for elementary stream n |
| MBS<sub>n</sub> | is the size of the multiplexing buffer MBn, measured in bytes |
| EB<sub>n</sub> | is the elementary stream buffer for the AV1 video stream |
| EBS<sub>n</sub> | is the size of the multiplexing buffer MBn, measured in bytes |
| j | is an index to the AV1 access unit of the AV1 video stream |
| A<sub>n</sub>(j) | is the j-th access unit of the AV1 video bitstream |
| td<sub>n</sub> (j) | is the decoding time of An(j), measured in seconds, in the system target decoder |
| Rx<sub>n</sub> | is the transfer rate from the transport buffer TBn to the multiplex buffer MBn as specified below. |
| Rbx<sub>n</sub> | is the transfer rate from the multiplex buffer MBn to the elementary stream buffer EBn as specified below |

The following apply:
 * There is exactly one transport buffer TB<sub>n</sub> for the received AV1 video stream where the size TBS is fixed to 512 bytes.
 * There is exactly one multiplexing buffer MB<sub>n</sub> for the AV1 video stream, where the size MBS<sub>n</sub> of the multiplexing buffer MB is constrained as follows:  
 MBS<sub>n</sub> = BS<sub>mux</sub> + BS<sub>oh</sub> + 0.1 x BufferSize  
where BS<sub>oh</sub>, packet overhead buffering, is defined as:  
BS<sub>oh</sub> = (1/750) seconds × max{ 1100 × BitRate, 2 000 000 bit/s}  
and BS<sub>mux</sub>, additional mutliplex buffering, is defined as:  
BS<sub>mux</sub> = 0.004 seconds ×max{ 1100 × BitRate, 2 000 000 bit/s}  
BufferSize and BitRate are defined in Annex E of the AV1 Bitstream & Decoding Process Specification
 * There is exactly one elementary stream buffer EB<sub>n</sub> for all the elementary streams in the set of received elementary streams associated by hierarchy descriptors, with a total size EBS<sub>n</sub>:  
EBS<sub>n</sub> = BufferSize  
 * Transfer from TB<sub>n</sub> to MB<sub>n</sub> is applied as follows:  
When there is no data in TB<sub>n</sub> then Rx<sub>n</sub> is equal to zero. Otherwise:  
Rx<sub>n</sub> = 1.1 x BitRate
 * The leak method shall be used to transfer data from MB<sub>n</sub> to EB<sub>n</sub> as follows:  
Rbx<sub>n</sub> = 1.1 × BitRate

> NOTE: markdown math doesn't seem to work with subscript

If there is PES packet payload data in MB<sub>n</sub>, and buffer EB<sub>n</sub> is not full, the PES packet payload is transferred from MB<sub>n</sub> to EB<sub>n</sub> at a rate equal to Rbx<sub>n</sub>. If EB<sub>n</sub> is full, data are not removed from MB<sub>n</sub>. When a byte of data is transferred from MB<sub>n</sub> to EB<sub>n</sub>, all PES packet header bytes that are in MB<sub>n</sub> and precede that byte are instantaneously removed and discarded. When there is no PES packet payload data present in MB<sub>n</sub>, no data is removed from MB<sub>n</sub>. All data that enters MB<sub>n</sub> leaves it. All PES packet payload data bytes enter EB<sub>n</sub> instantaneously upon leaving MB<sub>n</sub>.

### STD delay

The STD delay of any AV1 video through the system target decoders buffers TB<sub>n</sub>, MB<sub>n</sub>, and EB<sub>n</sub> shall be constrained by td<sub>n</sub>(j) – t(i) ≤ 10 seconds for all j, and all bytes i in access unit A<sub>n</sub>(j).

### Buffer management conditions

Transport streams shall be constructed so that the following conditions for buffer management are satisfied:  
* Each TB<sub>n</sub> shall not overflow and shall be empty at least once every second.
* Each MB<sub>n</sub>, EB<sub>n</sub> and Buffer Pool shall not overflow.
* EB<sub>n</sub> shall not underflow, except when the Operating parameters info syntax has low_delay_mode_flag set to '1'. Underflow of EB<sub>n</sub> occurs for AV1 access unit A<sub>n</sub>(j) when one or more bytes of A<sub>n</sub>(j) are not present in EB<sub>n</sub> at the decoding time td<sub>n</sub>(j).

## Definition of DTS and PTS

### PTS

If a PTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the PTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the PresentationTime in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

### DTS

If a DTS is present in the PES packet header, it shall refer to the first AV1 access unit that commences in this PES packet.

To achieve consistency between the STD model and the buffer model defined in Annex E of the AV1 Bitstream & Decoding Process Specification, for each AV1 access unit the DTS value in the STD shall, within the accuracy of their respective clocks, indicate the same instant in time as the ScheduledRemovalTiming in the decoder buffer model, as defined in Annex E of AV1 Bitstream & Decoding Process Specification.

## Administrativia

* finish by Tuesday night, for DVB
* Descriptor registration, format_identifier,
* code.videolan.org -> github.com/videolan/
* RFC first, then maybe ETSI standardisation




